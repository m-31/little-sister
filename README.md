# Little Sister

## Description
This is a web application that shows the status of various systems.


## Installation and local testing

### Prerequisites

#### Software
You should have Python 3.11 or later installed on your system.
Also, a running instance of Redis is required. 

#### Configuration

The allowed users must be defined in a `users.json` file. This file should be in the root directory of the project and
have the following format:

```json
{
    "jdoe": {
        "firstname": "Jane",
        "lastname": "Doe",
        "password": "test1234"
    },
    "amorgan": {
        "firstname": "Alex",
        "lastname": "Morgan",
        "password": "passw0rd"
    }
}
```
So with the credentials above, the allowed user 'jdoe' can log in with the password 'test1234'.

### Installation
```bash
python3 -m venv venv                  # Create a virtual environment
source venv/bin/activate              # Activate the virtual environment
pip install -r requirements.txt       # Install the required packages
gunicorn --bind 0.0.0.0:8000 app:app  # Run the application with gunicorn
```

On your browser, navigate to `http://localhost:8000` to see the application running.
