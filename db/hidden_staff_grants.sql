-- Shared reviewed grants; the caller owns the transaction and error policy.
-- Keep table-level SELECT revoked before narrower column-level grants.
REVOKE SELECT ON public.staff FROM nl2sql_reader;
GRANT SELECT (staff_id, first_name, last_name, address_id, email, store_id,
              active, username, last_update)
    ON public.staff TO nl2sql_reader;

-- Same for the view that exposes staff details.
REVOKE SELECT ON public.staff_list FROM nl2sql_reader;
