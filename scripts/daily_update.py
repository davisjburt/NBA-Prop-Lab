import sys, os, time, random, threading
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import customtkinter as ctk
from sqlalchemy.exc import IntegrityError
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

SEASON      = "2025-26"
MAX_WORKERS = 2

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT  = "#6366f1"
SUCCESS = "#10b981"
DANGER  = "#ef4444"
MUTED   = "#6b7280"
BG      = "#0f1117"
SURFACE = "#1a1d2e"
CARD    = "#1e2235"


class UpdaterApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._cancelled = False
        self.title("NBA Prop Lab — Daily Updater")
        self.geometry("720x580")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._cancel)  # handle red X button too
        self._build_ui()
        self.after(300, self.start_update)

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=72)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="Prop Lab Player Updater",
            font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
            text_color=ACCENT
        ).place(relx=0.5, rely=0.4, anchor="center")
        ctk.CTkLabel(
            header, text="Daily Stats Updater",
            font=ctk.CTkFont(size=12), text_color=MUTED
        ).place(relx=0.5, rely=0.75, anchor="center")

        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        stats_frame.pack(fill="x", padx=24, pady=(20, 0))

        self.stat_cards = {}
        for label, key, color in [
            ("Checking", "total",   "#ffffff"),
            ("Updated",  "updated", SUCCESS),
            ("Skipped",  "skipped", MUTED),
            ("Errors",   "errors",  DANGER),
        ]:
            card = ctk.CTkFrame(stats_frame, fg_color=CARD, corner_radius=12)
            card.pack(side="left", expand=True, fill="x", padx=6)
            val_lbl = ctk.CTkLabel(card, text="—", font=ctk.CTkFont(size=28, weight="bold"), text_color=color)
            val_lbl.pack(pady=(14, 2))
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont(size=11), text_color=MUTED).pack(pady=(0, 12))
            self.stat_cards[key] = val_lbl

        prog_frame = ctk.CTkFrame(self, fg_color="transparent")
        prog_frame.pack(fill="x", padx=24, pady=(20, 0))

        self.progress_bar = ctk.CTkProgressBar(prog_frame, height=8, progress_color=ACCENT, fg_color=SURFACE)
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)

        self.progress_label = ctk.CTkLabel(
            prog_frame, text="Starting...",
            font=ctk.CTkFont(size=12), text_color=MUTED
        )
        self.progress_label.pack(anchor="w", pady=(6, 0))

        self.log_box = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family="Menlo", size=12),
            fg_color=SURFACE, text_color="#c9d1d9",
            corner_radius=12, wrap="word",
            scrollbar_button_color=SURFACE,
        )
        self.log_box.pack(fill="both", expand=True, padx=24, pady=(16, 16))
        self.log_box.configure(state="disabled")

        # Starts as Cancel, switches to Close when done
        self.action_btn = ctk.CTkButton(
            self, text="Cancel",
            fg_color=SURFACE, hover_color=CARD,
            text_color=MUTED, font=ctk.CTkFont(size=13),
            corner_radius=10, command=self._cancel,
            state="normal"
        )
        self.action_btn.pack(pady=(0, 20), ipadx=20)

    def _cancel(self):
        self._cancelled = True
        try:
            self.quit()
            self.destroy()
        except Exception:
            pass

    def _finish(self):
        self.action_btn.configure(
            text="Close",
            fg_color=ACCENT,
            hover_color="#4f46e5",
            text_color="white",
            command=self._close
        )

    def _close(self):
        try:
            self.quit()
            self.destroy()
        except Exception:
            pass

    def log(self, msg):
        if self._cancelled:
            return
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def set_stat(self, key, value):
        if self._cancelled:
            return
        self.stat_cards[key].configure(text=str(value))

    def start_update(self):
        threading.Thread(target=self._run_update, daemon=True).start()

    def _run_update(self):
        from app import create_app
        from app.models.models import db, Player, PlayerGameStat
        from app.services.nba_fetcher import fetch_game_logs
        from nba_api.stats.endpoints import leaguegamelog
        from nba_api.stats.static import teams as nba_teams

        app = create_app()
        self.after(0, self.log, "⏳  Loading player list...")

        with app.app_context():
            players    = Player.query.all()
            player_map = {}
            for p in players:
                if p.team_abbr:
                    player_map.setdefault(p.team_abbr.upper(), []).append(p)

            global_last = db.session.query(
                db.func.max(PlayerGameStat.date)
            ).scalar()

            last_logged_map = {}
            for p in players:
                latest = db.session.query(
                    db.func.max(PlayerGameStat.date)
                ).filter_by(player_id=p.id).scalar()
                last_logged_map[p.id] = latest

        if self._cancelled:
            return

        self.after(0, self.log, f"✅  Loaded {len(players)} players")
        self.after(0, self.log, f"📅  Last logged game: {global_last or 'None'}\n")
        self.after(0, self.log, "🔍  Finding teams with new games...")

        try:
            time.sleep(0.6)
            game_log = leaguegamelog.LeagueGameLog(
                season=SEASON,
                season_type_all_star="Regular Season",
                date_from_nullable=str(global_last) if global_last else "",
                timeout=30
            )
            gdf        = game_log.get_data_frames()[0]
            id_to_abbr = {str(t["id"]): t["abbreviation"] for t in nba_teams.get_teams()}
            active_teams = set(
                id_to_abbr.get(str(int(tid)), "")
                for tid in gdf["TEAM_ID"].unique()
                if id_to_abbr.get(str(int(tid)))
            )
            self.after(0, self.log, f"🏀  {len(active_teams)} teams with new games: {', '.join(sorted(active_teams))}\n")
        except Exception as e:
            self.after(0, self.log, f"⚠️  Could not filter by team — checking all players ({e})")
            active_teams = set(player_map.keys())

        if self._cancelled:
            return

        with app.app_context():
            candidates      = []
            skipped_upfront = 0
            for p in players:
                team = (p.team_abbr or "").upper()
                if team in active_teams:
                    candidates.append((p.id, p.name, last_logged_map[p.id]))
                else:
                    skipped_upfront += 1

        total = len(candidates)
        self.after(0, self.set_stat, "total", total)
        self.after(0, self.set_stat, "skipped", skipped_upfront)
        self.after(0, self.log, f"⚡  Skipping {skipped_upfront} players on idle teams")
        self.after(0, self.log, f"✅  Checking {total} players on active teams\n")

        updated = 0
        errors  = 0
        done    = 0
        skipped = skipped_upfront

        def update_player(player_id, player_name, last_logged):
            if self._cancelled:
                return player_name, 0, None
            time.sleep(0.5 + random.uniform(0, 0.2))
            with app.app_context():
                try:
                    df = fetch_game_logs(player_id, season=SEASON)
                    if df.empty:
                        return player_name, 0, None

                    df["date"] = pd.to_datetime(df["date"]).dt.date
                    if last_logged:
                        last_logged_d = last_logged.date() if hasattr(last_logged, "date") else last_logged
                        df = df[df["date"] > last_logged_d]

                    if df.empty:
                        return player_name, 0, None

                    new_rows = 0
                    for _, row in df.iterrows():
                        try:
                            db.session.add(PlayerGameStat(
                                player_id=player_id,
                                date=row["date"],         matchup=row["matchup"],
                                location=row["location"],  min=row["min"],
                                pts=row["pts"],            reb=row["reb"],
                                ast=row["ast"],            stl=row["stl"],
                                blk=row["blk"],            fg3m=row["fg3m"],
                                tov=row["tov"]
                            ))
                            db.session.flush()
                            new_rows += 1
                        except IntegrityError:
                            db.session.rollback()

                    db.session.commit()
                    return player_name, new_rows, None
                except Exception as e:
                    db.session.rollback()
                    return player_name, 0, str(e)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(update_player, pid, name, last): name
                for pid, name, last in candidates
            }
            for future in as_completed(futures):
                if self._cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return

                name, new_rows, error = future.result()
                done += 1

                pct = done / total if total else 1
                self.after(0, self.progress_bar.set, pct)
                self.after(0, self.progress_label.configure,
                           {"text": f"Checking {name}  ({done}/{total})"})

                if error:
                    errors += 1
                    self.after(0, self.log, f"❌  {name} — {error[:60]}")
                    self.after(0, self.set_stat, "errors", errors)
                elif new_rows:
                    updated += 1
                    self.after(0, self.log, f"✅  {name} — +{new_rows} game{'s' if new_rows > 1 else ''}")
                    self.after(0, self.set_stat, "updated", updated)
                else:
                    skipped += 1
                    if skipped % 10 == 0:
                        self.after(0, self.set_stat, "skipped", skipped)

        if self._cancelled:
            return

        self.after(0, self.set_stat, "skipped", skipped)
        self.after(0, self.progress_bar.set, 1.0)
        self.after(0, self.progress_label.configure, {"text": "Complete!"})
        self.after(0, self.log, f"\n🏁  Done — {updated} updated · {skipped} skipped · {errors} errors")
        self.after(0, self._finish)


if __name__ == "__main__":
    app = UpdaterApp()
    app.mainloop()
