.PHONY: install-hooks test

install-hooks:
	ln -sf ../../.hooks/pre-commit .git/hooks/pre-commit
	ln -sf ../../.hooks/pre-push .git/hooks/pre-push
	@echo "Hooks installed. Run 'make test' to verify."

test:
	uv run pytest
