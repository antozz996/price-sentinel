# Project Rules & Guidelines

## ⚠️ CRITICAL CONSTRAINTS

### Database Data Protection (DO NOT RESET / DELETE)
- **NEVER** run commands or scripts that clear, truncate, drop, recreate, reset, or re-seed the PostgreSQL database tables.
- **NEVER** run schema drops (`DROP SCHEMA public CASCADE`) or invoke database initialization scripts (`create_db.py`, `clear_db.py`, `seed.py`) unless explicitly requested by the user.
- The database now contains **real business data and invoices uploaded by the user**, which must be preserved under all circumstances.

### Repository Data Hygiene
- **NEVER** commit database dumps, raw production exports, invoices, uploaded business documents, credentials, tokens, private keys, or runtime `.env` files.
- Database backups must live in an approved private backup location outside Git. Before adding any `.sql`, `.dump`, `.backup`, archive, or large data export, stop and verify that it contains no real business/customer data.
