# Authentication update

The project now supports both existing-user login and new-user account creation.

## Existing users
Open `/login` and sign in with the existing username and password.

## New users
From `/login`, choose **Create a new account** or open `/register`.

A new account creates a database record in the existing `users` table with:
- role: `FIELD_SUPERVISOR`
- active status: enabled
- password stored as a PBKDF2-SHA256 hash
- empty district/cluster scope lists

After registration, the user is returned to the login page and can sign in normally.

No OCR, ingestion, validation, dashboard, or existing pipeline functionality was intentionally changed.
