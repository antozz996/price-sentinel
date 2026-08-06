-- Minimal base schema for the disposable Smart Price Sheet integration database.
-- This file is never intended for production.
create type ruolo_utente as enum ('admin', 'manager');
create type tipologia_location as enum ('balneare', 'ristorante', 'discoteca', 'evento');
create type pfa_tipo as enum ('percentuale', 'fisso', 'scaglioni');

create table location (
  id serial primary key,
  nome_struttura varchar(255) not null,
  piva_riferimento varchar(11) not null unique,
  tipologia tipologia_location not null
);
create table utenti (
  id serial primary key,
  email varchar(255) not null unique,
  password_hash varchar(255) not null,
  ruolo ruolo_utente not null,
  location_id integer references location(id) on delete set null,
  telegram_chat_id varchar(50),
  refresh_token_version integer not null default 1,
  attivo boolean not null default true
);
create table fornitori (
  id serial primary key,
  partita_iva varchar(11) not null unique,
  nome_azienda varchar(255) not null,
  attivo_whitelist boolean not null default true,
  email_contatto varchar(255)
);
create table products (
  id serial primary key,
  sku_interno varchar(100),
  canonical_name varchar(255) not null,
  normalized_name varchar(255),
  brand varchar(100), category varchar(100), subcategory varchar(100), variant varchar(100),
  volume_ml integer, weight_g integer, unit_count integer default 1,
  container_type varchar(50), comparison_unit varchar(50) not null,
  is_commodity boolean not null default false, is_active boolean not null default true,
  created_at timestamptz not null, updated_at timestamptz not null
);
create table supplier_product_aliases (
  id serial primary key,
  supplier_id integer not null references fornitori(id) on delete cascade,
  product_id integer not null references products(id) on delete cascade,
  supplier_code varchar(100), raw_description varchar(255) not null,
  normalized_description varchar(255) not null, ean varchar(50), pack_qty integer,
  volume_ml integer, weight_g integer, container_type varchar(50),
  status varchar(50) not null default 'approved', confidence_score numeric(5,2) not null default 1,
  source varchar(50) not null, first_seen_at timestamptz not null,
  last_seen_at timestamptz not null, created_at timestamptz not null, updated_at timestamptz not null,
  constraint uq_supplier_product_aliases_code unique(supplier_id, supplier_code)
);
create table listino_master (
  id serial primary key,
  fornitore_id integer not null references fornitori(id) on delete restrict,
  sku_interno varchar(100) not null, descrizione text not null,
  prezzo_pattuito numeric(12,4) not null, unita_misura varchar(20) not null,
  data_inizio_validita date not null, data_scadenza date,
  pfa_tipo pfa_tipo, pfa_valore numeric(10,4),
  supplier_product_alias_id integer references supplier_product_aliases(id) on delete set null
);
create table fatture (id serial primary key, fornitore_id integer not null references fornitori(id));
create table righe_fattura (
  id serial primary key,
  fattura_id integer not null references fatture(id),
  sku_interno varchar(100),
  prezzo_netto_normalizzato numeric(12,4),
  is_omaggio boolean default false
);
create table product_equivalence_group_items (group_id integer not null, product_id integer not null);
