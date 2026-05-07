.PHONY: up install seed fda-list openfda checks

up:
	docker compose up -d

install:
	pip install -r requirements.txt

seed:
	python -m src.ingest_seed_devices --path data/seed_devices.csv

fda-list:
	python -m src.ingest_fda_ai_list --panel Radiology --limit 20 --out data/fda_ai_list_radiology_latest.csv

openfda:
	python -m src.ingest_openfda --sources 510k,event,enforcement,recall --max-devices 20 --max-event-records-per-device 100 --max-recall-records-per-device 50

checks:
	psql "$${DATABASE_URL}" -f sql/example_queries.sql
