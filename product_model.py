from dataclasses import dataclass, field, asdict
from typing import Dict, List

@dataclass
class Product:
    source: str
    source_url: str
    external_id: str
    manufacturer: str
    model: str
    sku: str
    name: str
    category: str = ""
    series: str = ""
    description: str = ""
    price: str = ""
    attributes: Dict[str, str] = field(default_factory=dict)
    documents: List[dict] = field(default_factory=list)
    images: List[str] = field(default_factory=list)

    @property
    def dedupe_key(self):
        return f"{self.manufacturer.strip().lower()}::{self.model.strip().lower()}"

    @property
    def quality(self):
        n = len(self.attributes)
        if n >= 10:
            return "GOOD"
        if n >= 5:
            return "NORMAL"
        return "POOR"

    def apply_policy(self, policy: dict):
        if not policy.get("parse_images", False):
            self.images = []
        if not policy.get("parse_documents", True):
            self.documents = []
        if not policy.get("parse_description", True):
            self.description = ""
        if not policy.get("parse_price", False):
            self.price = ""
        if not policy.get("parse_attributes", True):
            self.attributes = {}
        if not policy.get("parse_category", True):
            self.category = ""
        if not policy.get("parse_manufacturer", True):
            self.manufacturer = ""
        return self

    def to_dict(self):
        d = asdict(self)
        d["dedupe_key"] = self.dedupe_key
        d["quality"] = self.quality
        return d
