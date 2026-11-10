"""Synthetic, immutable test scenarios — no production CRM data or tokens."""
BELLHAVEN = "PARENT_BELLHAVEN"
OTHER = "PARENT_OTHER"


def facility(name, street, city, state="OH", zip_code="44000", care="Assisted Living"):
    return {
        "name": name, "address": street, "city": city, "state": state,
        "zip": zip_code, "care_offerings": care,
        "source_url": "https://example.invalid/facility", "needs_address_review": "False",
    }


def account(account_id, name, street, city, state="OH", zip_code="44000",
            parent=OTHER, revenue="0", ar="0", care="Assisted Living", **fields):
    return {
        "account_id": account_id, "name": name, "billing_street": street,
        "billing_city": city, "billing_state": state, "billing_zip": zip_code,
        "parent_id": parent, "parent_name": "Test Parent", "care_type": care,
        "lifetime_revenue": revenue, "outstanding_ar": ar,
        "chow_current_account": "", "duplicate_of_account": "", "status": "Active",
        "note": "", **fields,
    }


def scenario(name):
    """Return (website record, CRM records, expected action, expected match status)."""
    if name == "cross_state":
        return (facility("Amberly Manor", "4390 Darrow Rd", "Hudson", "OH", "44236"),
                [account("CO_1", "Amberly Manor", "4390 Darrow Rd", "Hudson", "CO", "44236")],
                "REVIEW_CREATE", "NO_MATCH")
    if name == "chow":
        return (facility("Bellhaven of Marietta", "100 River Rd", "Marietta", zip_code="45750"),
                [account("OLD_M", "Bellhaven of Marietta", "100 River Rd", "Marietta",
                         zip_code="45750", revenue="51250", ar="3800")],
                "CHOW", "CONFIDENT_MATCH")
    if name == "chow_ar_zero":
        return (facility("Bellhaven of Tiffin", "200 Main St", "Tiffin", zip_code="44883"),
                [account("OLD_T", "Bellhaven of Tiffin", "200 Main St", "Tiffin",
                         zip_code="44883", revenue="84000", ar="0")],
                "REPARENT", "CONFIDENT_MATCH")
    if name == "reparent":
        return (facility("Bellhaven Crossings of Lima", "500 Elm St", "Lima", zip_code="45801"),
                [account("LIMA_1", "Bellhaven Crossings of Lima", "500 Elm St", "Lima",
                         zip_code="45801", revenue="47000", ar="0")],
                "REPARENT", "CONFIDENT_MATCH")
    if name == "reparent_fixed":
        return (facility("Bellhaven Crossings of Lima", "500 Elm St", "Lima", zip_code="45801"),
                [account("LIMA_1", "Bellhaven Crossings of Lima", "500 Elm St", "Lima",
                         zip_code="45801", parent=BELLHAVEN)],
                "NO_ACTION", "CONFIDENT_MATCH")
    if name == "major_rename":
        return (facility("Bellhaven of Chesterton", "1250 NW Franklin St", "Chesterton", "IN", "46304"),
                [account("CH_1", "Chesterton Senior Commons", "1250 Northwest Franklin Street",
                         "Chesterton", "IN", "46304", parent=BELLHAVEN)],
                "INVESTIGATE", "CONFIDENT_MATCH")
    if name == "duplicate_address":
        return (facility("Bellhaven of Owosso", "1120 W Main St", "Owosso", "MI", "48867"),
                [account("OW_1", "Bellhaven of Owosso", "1120 W Main St", "Owosso",
                         "MI", "48867", parent=BELLHAVEN),
                 account("OW_2", "Bellhaven of Owosso", "1120 West Main Street", "Owosso",
                         "MI", "48867", parent=BELLHAVEN)],
                "INVESTIGATE", "MULTIPLE_ACCOUNTS")
    if name == "wrong_zip":
        return (facility("Bellhaven of Portsmouth", "250 Walnut St", "Portsmouth", zip_code="45662"),
                [account("PORT_1", "Bellhaven of Portsmouth", "250 Walnut St", "Portsmouth",
                         zip_code="45626", parent=BELLHAVEN)],
                "UPDATE_FIELDS", "CONFIDENT_MATCH")
    raise KeyError(name)
