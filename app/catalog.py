from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VmOffer:
    vm_id: str
    name: str
    cpu: int
    ram_gb: int
    disk_gb: int
    bandwidth_tb: int
    price_rub: int


COUNTRIES: dict[str, str] = {
    "ph": "Филиппины 🇵🇭",
    "de": "Германия 🇩🇪",
    "nl": "Нидерланды 🇳🇱",
    "pl": "Польша 🇵🇱",
    "fi": "Финляндия 🇫🇮",
    "tr": "Турция 🇹🇷",
}

SOLD_OUT_COUNTRIES: set[str] = {"nl", "tr"}

OFFERS_BY_COUNTRY: dict[str, list[VmOffer]] = {
    "ph": [
        VmOffer("ph-1", "PH Basic", 2, 4, 60, 2, 1990),
        VmOffer("ph-2", "PH Standard", 4, 8, 120, 4, 3290),
        VmOffer("ph-3", "PH Pro", 8, 16, 240, 8, 5490),
    ],
    "de": [
        VmOffer("de-1", "DE Basic", 2, 4, 80, 3, 2190),
        VmOffer("de-2", "DE Standard", 4, 8, 160, 5, 3590),
        VmOffer("de-3", "DE Pro", 8, 16, 320, 10, 5990),
    ],
    "nl": [
        VmOffer("nl-1", "NL Basic", 2, 4, 70, 3, 2090),
        VmOffer("nl-2", "NL Standard", 4, 8, 140, 6, 3390),
        VmOffer("nl-3", "NL Pro", 8, 16, 280, 9, 5790),
    ],
    "pl": [
        VmOffer("pl-1", "PL Basic", 2, 4, 60, 3, 1890),
        VmOffer("pl-2", "PL Standard", 4, 8, 120, 5, 3190),
        VmOffer("pl-3", "PL Pro", 8, 16, 240, 8, 5390),
    ],
    "fi": [
        VmOffer("fi-1", "FI Basic", 2, 4, 90, 3, 2290),
        VmOffer("fi-2", "FI Standard", 4, 8, 180, 6, 3690),
        VmOffer("fi-3", "FI Pro", 8, 16, 360, 10, 6190),
    ],
    "tr": [
        VmOffer("tr-1", "TR Basic", 2, 4, 50, 2, 1790),
        VmOffer("tr-2", "TR Standard", 4, 8, 100, 4, 2990),
        VmOffer("tr-3", "TR Pro", 8, 16, 220, 7, 5090),
    ],
}


def get_offers(country_code: str) -> list[VmOffer]:
    offers = OFFERS_BY_COUNTRY.get(country_code, [])
    return sorted(offers, key=lambda vm: vm.price_rub)


def find_offer(country_code: str, vm_id: str) -> VmOffer | None:
    for offer in OFFERS_BY_COUNTRY.get(country_code, []):
        if offer.vm_id == vm_id:
            return offer
    return None


def is_country_available(country_code: str) -> bool:
    return country_code not in SOLD_OUT_COUNTRIES
