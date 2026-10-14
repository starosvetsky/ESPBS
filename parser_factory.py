from parsers.eltex import EltexParser
from parsers.olnisa import OlnisaParser
from parsers.industryport import IndustryPortParser

PARSERS = {
    "eltex": EltexParser,
    "olnisa": OlnisaParser,
    "industryport": IndustryPortParser,
}

def create_parser(parser_name: str, policy: dict):
    cls = PARSERS.get(parser_name)
    if not cls:
        raise ValueError(f"Неизвестный parser: {parser_name}")
    return cls(policy)
