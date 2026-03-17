#!/bin/bash
python3 scripts/fetch_data.py && git add data/ && git diff --staged --quiet || git commit -m "chore: refresh data" && git push
