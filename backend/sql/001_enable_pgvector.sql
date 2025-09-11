-- Migration stub to enable pgvector in Supabase.
-- Run this in Supabase Studio (SQL Editor) or via psql connected to your project's database.
-- This operation needs to be performed once per database.

create extension if not exists vector;
