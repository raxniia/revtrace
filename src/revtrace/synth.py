from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

START = datetime(2026, 8, 1)
DAYS = 92
SHOCK_MONTH = 10

PRODUCTS = {
    "Salon Moderne": (185_000, 0.28, 0.150),
    "Chambre Adulte": (240_000, 0.20, 0.130),
    "Matelas Orthopédique": (48_000, 0.22, 0.170),
    "Cuisine Équipée": (420_000, 0.30, 0.045),
}
SOURCES = {"Instagram": 0.34, "Facebook": 0.30, "Site web": 0.18, "Recommandation": 0.10, "Salon": 0.08}
WILAYAS = ["Alger", "Oran", "Blida", "Sétif", "Constantine", "Tizi Ouzou", "Béjaïa", "Annaba"]
FIRST_NAMES = [
    "Amina",
    "Yacine",
    "Sofiane",
    "Lina",
    "Karima",
    "Walid",
    "Nesrine",
    "Mehdi",
    "Imane",
    "Rachid",
    "Sara",
    "Bilal",
    "Houda",
    "Nabil",
    "Meriem",
    "Anis",
    "Kenza",
    "Farid",
    "Asma",
    "Hichem",
]
LAST_NAMES = [
    "Benali",
    "Boudiaf",
    "Haddad",
    "Mansouri",
    "Saidi",
    "Belkacem",
    "Brahimi",
    "Cherif",
    "Djebbar",
    "Ferhat",
    "Hamidi",
    "Kaci",
    "Larbi",
    "Meziane",
    "Ouali",
    "Rahmani",
    "Slimani",
    "Taleb",
    "Zerrouki",
]

OPENERS = {
    "Salon Moderne": [
        "Salam, chhal le salon moderne ?",
        "Bonjour, le salon 7 places mazal disponible ?",
        "Salam, nheb nchouf les couleurs ta3 salon moderne",
    ],
    "Chambre Adulte": [
        "Salam, chhal la chambre complète ?",
        "Bonjour, la chambre adulte fiha armoire ?",
        "Svp prix ta3 chambre adulte w délai ?",
    ],
    "Matelas Orthopédique": [
        "Salam, matelas orthopédique 160x200 chhal ?",
        "Bonjour, le matelas fih garantie ?",
        "Kayen matelas orthopédique ferme ?",
    ],
    "Cuisine Équipée": [
        "Salam, nheb cuisine équipée 3 mètres, chhal ?",
        "Bonjour, vous faites la cuisine sur mesure ?",
        "Svp prix ta3 cuisine équipée m3a électroménager ?",
    ],
}
REPLIES = [
    "Bonjour ! Le prix est de {price} DA, livraison incluse sur {wilaya}.",
    "Salam, merci pour votre message. Prix : {price} DA. Disponible en 3 couleurs.",
    "Bonjour, oui disponible. Le tarif est {price} DA, paiement à la livraison possible.",
]
KITCHEN_NOTICE = [
    "Pour la cuisine, le délai de fabrication et livraison est de 6 semaines.",
    "Attention, la cuisine équipée demande 6 semaines de délai.",
]
LATE = ["3lach ma jawbtounich bkri ?", "Ah enfin, kont rah nsit.", "J'ai attendu longtemps la réponse..."]
PRICE = ["Ghali chwiya, kayen remise ?", "Lqit arkhas f Facebook.", "C'est un peu cher pour moi."]
DELAY = [
    "6 semaines bezzaf, ma nqderch nstanna.",
    "Le délai est trop long, désolé.",
    "Khassni cuisine qbel l'3ers, 6 semaines bezzaf.",
]
THINKING = [
    "Ok nchouf w nwalilek.",
    "Je vais réfléchir et je reviens vers vous.",
    "Ndir l'compte w n3ayetlek.",
]
FOLLOWUP = [
    "Bonjour, je reviens vers vous pour le {product}. Vous avez pu réfléchir ?",
    "Salam, mazal intéressé(e) par {product} ? On peut vous proposer une facilité.",
]
WIN = ["Ok, nconfirmi la commande.", "D'accord, je prends. Livraison quand ?", "Saha, sajjelli la commande."]
GONE = ["Merci, c'est bon j'ai trouvé ailleurs.", "Chrit men 3and wahed akhor, merci."]


@dataclass(frozen=True)
class Scenario:
    name: str = "dar-confort"
    seed: int = 42
    slow_response: bool = True
    missing_followups: bool = True
    bad_source: bool = False
    price_hike: bool = False

    def truth(self) -> dict:
        primary = []
        if self.slow_response:
            primary.append("response")
        if self.missing_followups:
            primary.append("followups")
        if self.bad_source:
            primary.append("source")
        if self.price_hike:
            primary.append("price")
        return {
            "scenario": asdict(self),
            "primary": primary,
            "chronic": ["product"],
            "decoys": [] if self.price_hike else ["price"],
        }


class _Generator:
    def __init__(self, scenario: Scenario):
        self.s = scenario
        self.rng = np.random.default_rng(scenario.seed)
        self.py = random.Random(scenario.seed)

    def shocked(self, day: datetime) -> bool:
        return day.month >= SHOCK_MONTH

    def team(self, day: datetime) -> dict[str, float]:
        if self.s.slow_response and self.shocked(day):
            return {"Amine": 0.30, "Sara": 0.30, "Karim": 0.40}
        return {"Amine": 0.35, "Sara": 0.35, "Yacine": 0.30}

    def response_minutes(self, rep: str, day: datetime) -> float:
        median = {"Amine": 22, "Sara": 18, "Yacine": 25, "Karim": 190}[rep]
        if self.s.slow_response and self.shocked(day) and rep != "Karim":
            median *= 2.6
        return round(float(max(2, self.rng.lognormal(np.log(median), 0.7))), 1)

    def source(self, day: datetime) -> str:
        weights = dict(SOURCES)
        if self.s.bad_source and self.shocked(day):
            weights = {k: v * 0.62 for k, v in weights.items()} | {"TikTok Ads": 0.38}
        names = list(weights)
        p = np.array(list(weights.values()))
        return str(self.rng.choice(names, p=p / p.sum()))

    def price(self, base: int, day: datetime) -> int:
        low, high = (1.0, 1.2) if self.s.price_hike and self.shocked(day) else (0.88, 1.12)
        return int(round(base * self.rng.uniform(low, high), -2))

    def conversation(self, lead: dict, won: bool, reason: str | None) -> list[dict]:
        pick = self.py.choice
        t = lead["created_at"]
        rep = lead["sales_rep"]
        messages = [{"from": "client", "at": t.isoformat(), "text": pick(OPENERS[lead["product"]])}]
        t += timedelta(minutes=lead["first_response_minutes"])
        price = f"{lead['price_quoted']:,}".replace(",", " ")
        reply = pick(REPLIES).format(price=price, wilaya=lead["wilaya"])
        messages.append({"from": "agent", "agent": rep, "at": t.isoformat(), "text": reply})
        if lead["product"] == "Cuisine Équipée":
            t += timedelta(minutes=1)
            messages.append(
                {"from": "agent", "agent": rep, "at": t.isoformat(), "text": pick(KITCHEN_NOTICE)}
            )
        if lead["first_response_minutes"] > 120 and self.py.random() < 0.55:
            t += timedelta(minutes=self.py.randint(5, 90))
            messages.append({"from": "client", "at": t.isoformat(), "text": pick(LATE)})

        def follow_up():
            nonlocal t
            t += timedelta(hours=self.py.randint(20, 60))
            text = pick(FOLLOWUP).format(product=lead["product"])
            messages.append({"from": "agent", "agent": rep, "at": t.isoformat(), "text": text})

        if won:
            if self.py.random() < 0.25:
                t += timedelta(minutes=self.py.randint(10, 300))
                messages.append({"from": "client", "at": t.isoformat(), "text": pick(PRICE)})
            if lead["followups_count"] >= 2:
                follow_up()
            t += timedelta(minutes=self.py.randint(10, 600))
            messages.append({"from": "client", "at": t.isoformat(), "text": pick(WIN)})
            return messages

        t += timedelta(minutes=self.py.randint(10, 600))
        text = pick(PRICE if reason == "prix" else DELAY if reason == "délai livraison" else THINKING)
        messages.append({"from": "client", "at": t.isoformat(), "text": text})
        if lead["followups_count"] >= 2:
            follow_up()
            if self.py.random() < 0.5:
                t += timedelta(hours=self.py.randint(1, 30))
                messages.append({"from": "client", "at": t.isoformat(), "text": pick(GONE)})
        return messages

    def lead(self, lead_id: int, day: datetime) -> tuple[dict, bool, str | None]:
        rng = self.rng
        product = str(rng.choice(list(PRODUCTS), p=[v[1] for v in PRODUCTS.values()]))
        base_price, _, base_rate = PRODUCTS[product]
        team = self.team(day)
        rep = str(rng.choice(list(team), p=list(team.values())))
        minutes = self.response_minutes(rep, day)
        price = self.price(base_price, day)
        ratio = price / base_price
        band = "bas" if ratio < 0.95 else "standard" if ratio <= 1.05 else "haut"
        qualified = bool(rng.random() < 0.62)
        source = self.source(day)
        second = 0.50 if self.s.missing_followups and self.shocked(day) else 0.70
        followups = 1 + int(rng.random() < second) + int(rng.random() < 0.25)

        p = base_rate * 1.6
        p *= 1.0 if minutes <= 30 else 0.72 if minutes <= 120 else 0.38
        p *= 1.0 if followups >= 2 else 0.50
        p *= 1.0 if qualified else 0.35
        if source == "TikTok Ads":
            p *= 0.30
        if self.s.price_hike:
            p *= {"bas": 1.25, "standard": 1.0, "haut": 0.50}[band]
        won = bool(rng.random() < min(p, 0.9))

        reason = None
        if not won:
            price_talk = 0.55 if self.s.price_hike and band == "haut" else 0.31
            if product == "Cuisine Équipée" and rng.random() < 0.58:
                reason = "délai livraison"
            elif rng.random() < price_talk:
                reason = "prix"
            else:
                reason = "pas de réponse" if rng.random() < 0.5 else "inconnu"

        record = {
            "lead_id": f"L{lead_id:05d}",
            "created_at": day + timedelta(minutes=int(rng.integers(8 * 60, 22 * 60))),
            "source": source,
            "product": product,
            "wilaya": str(rng.choice(WILAYAS)),
            "sales_rep": rep,
            "first_response_minutes": minutes,
            "followups_count": followups,
            "qualified": qualified,
            "price_quoted": price,
            "price_band": band,
            "status": "won" if won else "lost",
            "lost_reason": reason or "",
        }
        return record, won, reason

    def build(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict]]:
        leads, conversations = [], []
        lead_id = 1
        for offset in range(DAYS):
            day = START + timedelta(days=offset)
            busy = self.s.slow_response and self.shocked(day)
            for _ in range(int(self.rng.poisson(60 if busy else 50))):
                record, won, reason = self.lead(lead_id, day)
                leads.append(record)
                conversations.append(
                    {
                        "lead_id": record["lead_id"],
                        "channel": "whatsapp" if self.rng.random() < 0.6 else "instagram",
                        "messages": self.conversation(record, won, reason),
                    }
                )
                lead_id += 1

        frame = pd.DataFrame(leads)
        customers, orders = [], []
        for i, row in enumerate(frame[frame.status == "won"].itertuples(index=False), start=1):
            customer_id = f"C{i:05d}"
            ordered = row.created_at + timedelta(days=int(self.rng.integers(1, 8)))
            customers.append(
                {
                    "customer_id": customer_id,
                    "lead_id": row.lead_id,
                    "name": f"{self.py.choice(FIRST_NAMES)} {self.py.choice(LAST_NAMES)}",
                    "wilaya": row.wilaya,
                    "first_order_at": ordered.date().isoformat(),
                }
            )
            orders.append(
                {
                    "order_id": f"O{len(orders) + 1:05d}",
                    "customer_id": customer_id,
                    "lead_id": row.lead_id,
                    "product": row.product,
                    "amount_dzd": int(round(row.price_quoted * self.rng.uniform(0.95, 1.0), -2)),
                    "order_date": ordered.date().isoformat(),
                }
            )
        frame["created_at"] = frame.created_at.dt.strftime("%Y-%m-%dT%H:%M:%S")
        return frame, pd.DataFrame(customers), pd.DataFrame(orders), conversations


def generate(scenario: Scenario, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    leads, customers, orders, conversations = _Generator(scenario).build()
    leads.to_csv(out_dir / "leads.csv", index=False)
    customers.to_csv(out_dir / "customers.csv", index=False)
    orders.to_csv(out_dir / "orders.csv", index=False)
    (out_dir / "conversations.json").write_text(
        json.dumps(conversations, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return scenario.truth()


def scenario_suite(count: int, seed: int = 7) -> list[Scenario]:
    combos = [
        (True, False, False, False),
        (False, True, False, False),
        (False, False, True, False),
        (False, False, False, True),
        (True, True, False, False),
        (True, False, True, False),
        (False, True, True, False),
        (False, True, False, True),
    ]
    return [Scenario(f"scenario-{i + 1:02d}", seed + i, *combos[i % len(combos)]) for i in range(count)]
