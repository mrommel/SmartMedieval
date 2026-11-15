# define the name of the virtual environment directory
VENV := .venv

# Load .env file (silently ignored if missing) so that Makefile
# variables like OLLAMA_API_KEY are available for all targets.
-include .env

# default target_location, when make executed without arguments
all: venv

$(VENV)/bin/activate: requirements.txt
	python3 -m venv $(VENV)
	./$(VENV)/bin/pip install --upgrade pip
	./$(VENV)/bin/pip install --no-cache-dir -r requirements.txt

# venv is a shortcut target_location
venv: $(VENV)/bin/activate

run: venv
	./$(VENV)/bin/python manage.py runserver 8098

make_migrations: venv
	./$(VENV)/bin/python manage.py makemigrations
	./$(VENV)/bin/python manage.py sqlmigrate games 0004  # change this
	./$(VENV)/bin/python manage.py migrate

migrate: venv
	./$(VENV)/bin/python manage.py migrate --run-syncdb

createsuperuser: venv
	./$(VENV)/bin/python manage.py createsuperuser
	# mrommel + ???
