"""Reviewed provider metadata for existing demo datasets; no runtime value sampling.

Bank annotations are copied from db/financial/02_load.sql at the P00 merge.
Changes to this dictionary require review; database comments are not exported.
"""

VERSION = "approved-metadata-v1"
BANK_TABLES = frozenset(
    {"district", "account", "client", "disp", "card", "loan", "order", "trans"}
)
PAGILA_TABLES = frozenset(
    {
        "actor",
        "address",
        "category",
        "city",
        "country",
        "customer",
        "film",
        "film_actor",
        "film_category",
        "inventory",
        "language",
        "payment",
        "rental",
        "staff",
        "store",
    }
)
COMMENTS = {
    "account": "Bank accounts.",
    "account.date": "Date the account was opened.",
    "account.frequency": "Statement frequency: POPLATEK MESICNE = monthly, "
    "POPLATEK TYDNE = weekly, POPLATEK PO OBRATU = after "
    "each transaction.",
    "card": "Credit cards, issued to a disposition (a client on an account).",
    "card.type": "Card type: junior, classic or gold.",
    "client": "Bank customers.",
    "disp": "Links clients to accounts: who owns or may use each account.",
    "disp.type": "OWNER = account owner, DISPONENT = authorized user.",
    "district": "Demographics for each district.",
    "district.a10": "Share of urban inhabitants, percent.",
    "district.a11": "Average salary.",
    "district.a12": "Unemployment rate in 1995, percent.",
    "district.a13": "Unemployment rate in 1996, percent.",
    "district.a14": "Entrepreneurs per 1000 inhabitants.",
    "district.a15": "Crimes committed in 1995.",
    "district.a16": "Crimes committed in 1996.",
    "district.a2": "District name.",
    "district.a3": "Region.",
    "district.a4": "Number of inhabitants.",
    "district.a5": "Municipalities with fewer than 500 inhabitants.",
    "district.a6": "Municipalities with 500 to 1999 inhabitants.",
    "district.a7": "Municipalities with 2000 to 9999 inhabitants.",
    "district.a8": "Municipalities with 10000 or more inhabitants.",
    "district.a9": "Number of cities.",
    "loan": "Loans granted to accounts. Amounts in Czech crowns (CZK).",
    "loan.duration": "Loan length in months.",
    "loan.payments": "Monthly payment.",
    "loan.status": "A = finished, paid off; B = finished, not paid; C = running, "
    "payments on time; D = running, client in debt.",
    "order": "Standing payment orders from an account. Amounts in Czech crowns "
    "(CZK).",
    "order.account_to": "Recipient account number.",
    "order.bank_to": "Recipient bank code.",
    "order.k_symbol": "Purpose: POJISTNE = insurance, SIPO = household bills, "
    "LEASING = leasing, UVER = loan payment; empty = not given.",
    "trans": "Account transactions, 1993 to 1998. Amounts in Czech crowns (CZK).",
    "trans.account": "Partner account number, for transfers.",
    "trans.balance": "Account balance after the transaction.",
    "trans.bank": "Partner bank code, for transfers.",
    "trans.k_symbol": "Purpose: POJISTNE = insurance, SLUZBY = statement fee, "
    "UROK = interest credited, SANKC. UROK = penalty interest "
    "on a negative balance, SIPO = household bills, DUCHOD = "
    "pension, UVER = loan payment; empty or NULL = not given.",
    "trans.operation": "VYBER KARTOU = card withdrawal, VKLAD = cash deposit, "
    "PREVOD Z UCTU = transfer in from another bank, VYBER = "
    "cash withdrawal, PREVOD NA UCET = transfer out to another "
    "bank.",
    "trans.type": "PRIJEM = credit (money in), VYDAJ = debit (money out), VYBER = "
    "cash withdrawal.",
}
# Static code dictionaries, not observations of rows. District/person names are absent.
VALUES = {
    ("account", "frequency"): (
        "POPLATEK MESICNE",
        "POPLATEK TYDNE",
        "POPLATEK PO OBRATU",
    ),
    ("disp", "type"): ("OWNER", "DISPONENT"),
    ("card", "type"): ("junior", "classic", "gold"),
    ("loan", "status"): ("A", "B", "C", "D"),
    ("trans", "type"): ("PRIJEM", "VYDAJ", "VYBER"),
    ("trans", "operation"): (
        "VYBER KARTOU",
        "VKLAD",
        "PREVOD Z UCTU",
        "VYBER",
        "PREVOD NA UCET",
    ),
    ("trans", "k_symbol"): (
        "POJISTNE",
        "SLUZBY",
        "UROK",
        "SANKC. UROK",
        "SIPO",
        "DUCHOD",
        "UVER",
        "' '",
    ),
    ("order", "k_symbol"): ("POJISTNE", "SIPO", "LEASING", "UVER", "''"),
}
ENUMS = {"mpaa_rating": ("G", "PG", "PG-13", "R", "NC-17")}
DOMAINS = {"year": "integer"}
