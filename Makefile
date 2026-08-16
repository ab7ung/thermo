PREFIX ?= /usr/local

.PHONY: test unit cli install uninstall lint

test: unit cli

unit:
	@python3 -m unittest discover -s tests -q

cli:
	@sh tests/test_cli.sh

lint:
	@python3 -m compileall -q thermo && echo "thermo compiles"

install:
	@install -m 755 thermo $(PREFIX)/bin/thermo
	@echo "installed $(PREFIX)/bin/thermo"

uninstall:
	@rm -f $(PREFIX)/bin/thermo
