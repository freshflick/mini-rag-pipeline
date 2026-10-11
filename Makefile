.PHONY: run validate test fuzz ui
run:
	python3 rag_pipeline.py
validate:
	python3 validate.py
test:
	python3 -m unittest discover -s tests -v
fuzz:
	python3 tests/fuzz_pipeline.py --seed 20261011
ui:
	npm run dev
