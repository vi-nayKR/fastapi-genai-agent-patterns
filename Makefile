PYTHON ?= python

.PHONY: eval eval-live data check compare-judge
eval:
	$(PYTHON) -m scripts.run_evaluation
eval-live:
	$(PYTHON) -m scripts.run_evaluation --live
compare-judge:
	$(PYTHON) -m scripts.compare_judge
data:
	$(PYTHON) -m scripts.generate_incidents
check:
	$(PYTHON) -m scripts.run_checks
