"""Avatar de la Daily Cyber News.

Gemini choisit la tenue dans une liste fermée de vêtements (VOCABULAIRE) ;
ce module dessine ensuite l'avatar en SVG à partir de pièces prédéfinies.
Rien n'est « inventé » par l'IA : si un vêtement n'est pas dans la liste,
il est simplement ignoré.
"""

PEAU = "#f1c9a5"
CHEVEUX = "#5a3825"

# --- Vocabulaire autorisé (nom affiché -> couleur) ---------------------------
HAUTS = {
    "t-shirt": "#f2f2f2",
    "chemise": "#cfe0f0",
    "chemisier": "#f3dfe6",
    "pull": "#c47a5a",
    "gros pull": "#e8d9bf",
    "sweat": "#8a8fa0",
}
BAS = {
    "jean": "#4a6fa5",
    "pantalon": "#3a3f4b",
    "jupe": "#6b3f5a",
    "robe": "#7a2e4d",  # remplace haut + bas
}
# nom -> (couleur, longueur : ordonnée du bas du manteau, matelassé ?)
VESTES = {
    "veste": ("#5b4a3a", 114, False),
    "blazer": ("#2f3b52", 116, False),
    "manteau": ("#b08a5a", 132, False),
    "long manteau": ("#8a6f4d", 150, False),
    "doudoune": ("#3f6b4f", 122, True),
    "doudoune longue": ("#3f6b4f", 148, True),
}
CHAUSSURES = {
    "baskets": "#f5f5f5",
    "bottines": "#4a2f20",
    "bottes": "#2b2420",
}
ACCESSOIRES = ["collant", "écharpe", "bonnet", "gants", "parapluie"]

VOCABULAIRE = {
    "hauts": list(HAUTS),
    "bas": list(BAS),
    "vestes": list(VESTES),
    "chaussures": list(CHAUSSURES),
    "accessoires": ACCESSOIRES,
}


def _darker(hex_color, f=0.78):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))


def normaliser(items):
    """Garde uniquement les pièces connues, dans un ordre cohérent, et complète
    ce qui manque (jamais d'avatar « nu »). Renvoie la liste des noms à afficher."""
    brut = [str(i).strip().lower() for i in (items or [])]
    connus = set(HAUTS) | set(BAS) | set(VESTES) | set(CHAUSSURES) | set(ACCESSOIRES)
    brut = [i for i in brut if i in connus]
    # dédoublonnage en gardant l'ordre
    vus, liste = set(), []
    for i in brut:
        if i not in vus:
            vus.add(i)
            liste.append(i)

    bas = next((i for i in liste if i in BAS), None)
    haut = next((i for i in liste if i in HAUTS), None)
    veste = next((i for i in liste if i in VESTES), None)
    chaussure = next((i for i in liste if i in CHAUSSURES), None)

    if bas == "robe":
        haut = None  # une robe remplace le haut
    elif bas is None:
        bas = "pantalon"
    if haut is None and bas != "robe":
        haut = "t-shirt" if veste is None else "pull"
    if chaussure is None:
        chaussure = "baskets"

    acc = [i for i in liste if i in ACCESSOIRES]
    if "collant" in acc and bas not in ("jupe", "robe"):
        acc.remove("collant")  # un collant n'a de sens que sous une jupe/robe

    final = [x for x in (bas if bas != "robe" else None, haut) if x]
    if bas == "robe":
        final = ["robe"]
    if veste:
        final.append(veste)
    if "collant" in acc:
        final.insert(1, "collant")
    final.append(chaussure)
    final += [a for a in acc if a != "collant"]
    return final


def dessiner(items):
    """Renvoie le SVG (chaîne) de l'avatar portant la tenue `items`."""
    items = normaliser(items)
    haut = next((i for i in items if i in HAUTS), None)
    bas = next((i for i in items if i in BAS), "pantalon")
    veste = next((i for i in items if i in VESTES), None)
    chaussure = next((i for i in items if i in CHAUSSURES), "baskets")
    collant = "collant" in items
    ecarpe = "écharpe" in items
    bonnet = "bonnet" in items
    gants = "gants" in items

    p = []  # pièces SVG, dans l'ordre de dessin (du fond vers l'avant)

    # Jambes
    if bas in ("jupe", "robe"):
        couleur_jambes = "#2b2b33" if collant else PEAU
    else:
        couleur_jambes = BAS[bas]
    p.append(f'<rect x="318" y="118" width="20" height="42" rx="4" fill="{couleur_jambes}"/>')
    p.append(f'<rect x="342" y="118" width="20" height="42" rx="4" fill="{couleur_jambes}"/>')

    # Chaussures
    couleur_ch = CHAUSSURES[chaussure]
    if chaussure == "baskets":
        for cx in (326, 354):
            p.append(f'<ellipse cx="{cx}" cy="162" rx="14" ry="6" fill="{couleur_ch}" stroke="#b5b5b5" stroke-width="0.5"/>')
    else:
        haut_botte = 138 if chaussure == "bottes" else 148
        for x in (318, 342):
            p.append(f'<rect x="{x}" y="{haut_botte}" width="20" height="{160 - haut_botte + 2}" rx="4" fill="{couleur_ch}"/>')
        for cx in (326, 354):
            p.append(f'<ellipse cx="{cx}" cy="162" rx="14" ry="6" fill="{couleur_ch}"/>')

    # Tronc (haut) ou robe
    if bas == "robe":
        c = BAS["robe"]
        p.append(f'<rect x="312" y="62" width="56" height="62" rx="10" fill="{c}"/>')
        p.append(f'<path d="M312 110 L368 110 L378 142 L302 142 Z" fill="{c}"/>')
        couleur_manches = c
    else:
        c = HAUTS[haut]
        p.append(f'<rect x="312" y="62" width="56" height="62" rx="10" fill="{c}"/>')
        if haut in ("pull", "gros pull", "sweat"):
            p.append(f'<rect x="327" y="57" width="26" height="10" rx="5" fill="{_darker(c, 0.9)}"/>')
        couleur_manches = c
        if bas == "jupe":
            p.append(f'<path d="M312 112 L368 112 L376 138 L304 138 Z" fill="{BAS["jupe"]}"/>')

    # Veste / manteau / doudoune
    couleur_veste = None
    if veste:
        couleur_veste, bas_y, matelasse = VESTES[veste]
        hauteur = bas_y - 62
        p.append(f'<rect x="309" y="62" width="62" height="{hauteur}" rx="9" fill="{couleur_veste}"/>')
        # partie visible du haut au centre
        centre = HAUTS[haut] if haut else BAS["robe"]
        p.append(f'<rect x="334" y="62" width="12" height="{max(hauteur - 8, 10)}" fill="{centre}"/>')
        if matelasse:
            fonce = _darker(couleur_veste, 0.7)
            y = 77
            while y < bas_y - 4:
                p.append(f'<line x1="309" y1="{y}" x2="334" y2="{y}" stroke="{fonce}" stroke-width="1"/>')
                p.append(f'<line x1="346" y1="{y}" x2="371" y2="{y}" stroke="{fonce}" stroke-width="1"/>')
                y += 15
        couleur_manches = couleur_veste

    # Bras et mains
    p.append(f'<rect x="300" y="66" width="14" height="46" rx="7" fill="{couleur_manches}"/>')
    p.append(f'<rect x="366" y="66" width="14" height="46" rx="7" fill="{couleur_manches}"/>')
    couleur_mains = "#333a44" if gants else PEAU
    p.append(f'<circle cx="307" cy="116" r="5" fill="{couleur_mains}"/>')
    p.append(f'<circle cx="373" cy="116" r="5" fill="{couleur_mains}"/>')

    # Cou, tête, cheveux
    p.append(f'<ellipse cx="340" cy="40" rx="20" ry="22" fill="{CHEVEUX}"/>')
    p.append(f'<rect x="335" y="52" width="10" height="14" fill="{PEAU}"/>')
    p.append(f'<circle cx="340" cy="42" r="15" fill="{PEAU}"/>')
    p.append(f'<path d="M323 40 Q340 16 357 40 Q348 30 340 30 Q332 30 323 40Z" fill="{CHEVEUX}"/>')

    # Accessoires de tête et de cou
    if bonnet:
        p.append('<path d="M322 36 Q340 6 358 36 Z" fill="#34495e"/>')
        p.append('<rect x="321" y="32" width="38" height="8" rx="4" fill="#2c3e50"/>')
        p.append('<circle cx="340" cy="11" r="4" fill="#2c3e50"/>')
    if ecarpe:
        p.append('<rect x="327" y="58" width="26" height="10" rx="5" fill="#c0392b"/>')
        p.append('<rect x="344" y="64" width="9" height="28" rx="3" fill="#c0392b"/>')

    legende = ", ".join(items)
    return (
        '<svg class="avatar" viewBox="292 6 96 170" role="img" '
        f'aria-label="Avatar portant la tenue du jour : {legende}">' + "".join(p) + "</svg>"
    )


if __name__ == "__main__":
    # Petit test : python scripts/avatar.py -> écrit avatar_test.html
    tenues = [
        ["jean", "gros pull", "doudoune longue", "baskets", "bonnet", "écharpe"],
        ["jupe", "collant", "chemisier", "long manteau", "bottines"],
        ["robe", "blazer", "bottes"],
        ["pantalon", "chemise", "blazer", "bottines"],
        ["jean", "t-shirt", "baskets"],
    ]
    with open("avatar_test.html", "w", encoding="utf-8") as f:
        f.write("<body style='display:flex;gap:20px;font-family:sans-serif'>")
        for t in tenues:
            f.write("<div>" + dessiner(t).replace('class="avatar"', 'height="250"') + f"<p>{', '.join(normaliser(t))}</p></div>")
        f.write("</body>")
    print("avatar_test.html écrit")
