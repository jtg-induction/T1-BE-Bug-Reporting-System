# T1-BE-Bug-Reporting-System

# Getting Started

First clone the repository from Github and switch to the new directory:

    $ git clone https://github.com/jtg-induction/T1-BE-Bug-Reporting-System.git
    $ cd T1-BE-Bug-Reporting-System

Create virtual environment and install project dependencies:

    $ pipenv install

Then simply apply the migrations:

    $ python manage.py migrate

You can now run the development server:

    $ python manage.py runserver
