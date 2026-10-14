import json
from pathlib import Path

class SourcePolicyRegistry:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self.reload()

    def reload(self):
        self.data = json.loads(self.config_path.read_text(encoding="utf-8"))

    def save(self):
        self.config_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def domains(self):
        return [d for d, cfg in self.data.items() if cfg.get("enabled", True)]

    def get(self, domain):
        return self.data[domain]

    def update_flags(self, domain, flags: dict):
        if domain not in self.data:
            raise KeyError(domain)
        allowed = {
            "parse_images", "parse_documents", "parse_description",
            "parse_price", "parse_attributes", "parse_manufacturer",
            "parse_category"
        }
        for key, value in flags.items():
            if key in allowed:
                self.data[domain][key] = bool(value)
        self.save()

    def display_name(self, domain):
        return self.get(domain).get("display_name", domain)

    def parser_name(self, domain):
        return self.get(domain).get("parser", "")
