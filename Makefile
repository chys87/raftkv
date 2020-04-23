PROTOSRC := $(wildcard raftkv/*.proto)
PYSRC := $(filter-out %_pb2.py,$(wildcard raftkv/*.py))
PROTOPY := $(PROTOSRC:%.proto=%_pb2.py)
PYFLAKES := $(shell which pyflakes3 || echo pyflakes)

.PHONY: all clean pycodestyle pyflakes mypy

all: $(PROTOPY) pycodestyle pyflakes mypy
clean:
	rm -fv raftkv/*_pb2.py

$(PROTOPY): %_pb2.py: %.proto
	protoc --python_out=. $<

pycodestyle: $(PYSRC) | $(PROTOPY)
	pycodestyle $^

pyflakes: $(PYSRC) | $(PROTOPY)
	$(PYFLAKES) $^

mypy: $(PYSRC) | $(PROTOPY)
	mypy $^ || true
