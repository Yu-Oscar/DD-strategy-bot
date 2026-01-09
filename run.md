cd /Users/oscaryu/Documents/GitHub/DD-strategy-bot
source venv/bin/activate

python3 -X utf8 strategys/strategy_standx/maker_points.py -c config_maker_points.yaml --dry-run
python3 -X utf8 strategys/strategy_standx/maker_points.py -c config_maker_points.yaml