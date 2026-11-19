"""JSON Schemas describing every API response (the "contract" between backend and frontend).

All schemas are strict ("additionalProperties": false): if the backend adds, renames or removes
a field, or leaks one that should never be sent (such as password_hash), the schema test fails.
"""

MONEY = {"type": "string", "pattern": r"^\d+\.\d{2}$"}                 # DECIMAL(15,2) arrives as text
ISO_TIME = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"}
ID = {"type": "integer", "minimum": 1}
NULLABLE_ID = {"type": ["integer", "null"], "minimum": 1}
ROLE = {"enum": ["customer", "admin"]}
ACCOUNT_STATUS = {"enum": ["active", "frozen", "closed"]}
ACCOUNT_TYPE = {"enum": ["savings", "current"]}


def obj(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


def array_of(item):
    return {"type": "array", "items": item}


ERROR = obj({"error": {"type": "string", "minLength": 1}})

HEALTH = obj({"status": {"const": "ok"}, "message": {"type": "string"}})

USER_PUBLIC = obj({"user_id": ID, "name": {"type": "string"}, "email": {"type": "string", "format": "email"},
                   "role": ROLE})
LOGIN = obj({"message": {"type": "string"}, "token": {"type": "string", "pattern": r"^[\w-]+\.[\w-]+\.[\w-]+$"},
             "user": USER_PUBLIC})
REGISTER = obj({"message": {"type": "string"}, "user_id": ID})

PROFILE = obj({"user_id": ID, "name": {"type": "string"}, "email": {"type": "string"},
               "phone": {"type": ["string", "null"]}, "role": ROLE, "created_at": ISO_TIME})
PROFILE_UPDATED = obj({"message": {"type": "string"}, "user": PROFILE})

ACCOUNT = obj({"account_id": ID, "account_type": ACCOUNT_TYPE, "balance": MONEY, "status": ACCOUNT_STATUS,
               "created_at": ISO_TIME, "branch_name": {"type": "string"}, "ifsc_code": {"type": "string"}})
ACCOUNT_CREATED = obj({"message": {"type": "string"}, "account_id": ID})

TRANSACTION = obj({"transaction_id": ID, "from_account_id": NULLABLE_ID, "to_account_id": NULLABLE_ID,
                   "amount": MONEY, "type": {"enum": ["deposit", "withdrawal", "transfer"]},
                   "status": {"enum": ["pending", "success", "failed"]},
                   "description": {"type": ["string", "null"]}, "created_at": ISO_TIME})
STATEMENT_ITEM = {**TRANSACTION, "properties": {**TRANSACTION["properties"], "direction": {"enum": ["credit", "debit"]}},
                  "required": TRANSACTION["required"] + ["direction"]}
STATEMENT = obj({
    "account_id": ID, "current_balance": MONEY, "status": ACCOUNT_STATUS,
    "summary": obj({"total_credits": MONEY, "total_debits": MONEY, "transaction_count": {"type": "integer", "minimum": 0}}),
    "transactions": array_of(STATEMENT_ITEM)})

MONEY_RESULT = obj({"message": {"type": "string"}, "transaction_id": ID})

BRANCH = obj({"branch_id": ID, "branch_name": {"type": "string"}, "ifsc_code": {"type": "string"},
              "address": {"type": ["string", "null"]}})

ADMIN_STATS = obj({"totalUsers": {"type": "integer"}, "totalAccounts": {"type": "integer"},
                   "totalTransactions": {"type": "integer"}, "totalBalance": MONEY})
ADMIN_USER = obj({"user_id": ID, "name": {"type": "string"}, "email": {"type": "string"},
                  "phone": {"type": ["string", "null"]}, "role": ROLE, "created_at": ISO_TIME})
ADMIN_ACCOUNT = obj({"account_id": ID, "account_type": ACCOUNT_TYPE, "balance": MONEY, "status": ACCOUNT_STATUS,
                     "created_at": ISO_TIME, "user_id": ID, "owner_name": {"type": "string"},
                     "owner_email": {"type": "string"}, "branch_name": {"type": "string"}})
AUDIT_ROW = obj({"log_id": ID, "account_id": ID, "action": {"type": "string"},
                 "old_balance": MONEY, "new_balance": MONEY, "changed_at": ISO_TIME,
                 "owner_name": {"type": "string"}})
STATUS_UPDATED = obj({"message": {"type": "string"}})
