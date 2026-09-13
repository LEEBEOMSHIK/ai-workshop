FOLDER_NAME_WHITESPACE_V1: str = (
    "\u0009\u000a\u000b\u000c\u000d\u001c\u001d\u001e\u001f"
    "\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004"
    "\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f"
    "\u205f\u3000"
)


def folder_name_key(name: str) -> str:
    return name.strip(FOLDER_NAME_WHITESPACE_V1)
