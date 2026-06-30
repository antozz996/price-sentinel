# Project Rules & Guidelines

## ⚠️ CRITICAL CONSTRAINTS

### Database Data Protection (DO NOT RESET / DELETE)
- **NEVER** run commands or scripts that clear, truncate, drop, recreate, reset, or re-seed the PostgreSQL database tables.
- **NEVER** run schema drops (`DROP SCHEMA public CASCADE`) or invoke database initialization scripts (`create_db.py`, `clear_db.py`, `seed.py`) unless explicitly requested by the user.
- The database now contains **real business data and invoices uploaded by the user**, which must be preserved under all circumstances.
