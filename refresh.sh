# refresh.sh
#!/bin/bash
python scripts/fetch_data.py && git add data/ && git diff --staged --quiet || git commit -m "chore: refresh data" && git push