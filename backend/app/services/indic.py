"""
Indian-language shop speech to the romanised markers this product matches on.

Why this exists
------------------------------------------------------------------------------
Every keyword in this product is written the way a shopkeeper types it:
`baaki`, `udhaar`, `supplier`, `bijli`. Speech recognition returns the native
script instead, so the very same sentence arrives as `बाकी` in Hindi, `उधार`
in Marathi, `ବାକି` in Odia -- and matches nothing at all. The box hears the
merchant perfectly and then does nothing, which is worse than not hearing them.

Rather than duplicating every marker list once per language, text is normalised
once on the way in and all existing romanised matching keeps working unchanged.
Adding a language is adding a table here; no matcher changes.

------------------------------------------------------------------------------
This is deliberately NOT a transliterator
------------------------------------------------------------------------------
A general Indic romaniser is a hard problem and a wrong guess here silently
moves money. This is a closed vocabulary: only the words this product actually
branches on are mapped, plus digits. Anything else passes through untouched,
which degrades to "nothing understood" rather than to something wrong.

The normalised string is used ONLY for matching. Everything shown to the
merchant and everything stored keeps the original text, so a row in the books
always reads back as what was actually said, in the script it was said in.

------------------------------------------------------------------------------
Hindi and Marathi share Devanagari, on purpose
------------------------------------------------------------------------------
Both scripts are matched from one table. Where the two languages spell the same
concept differently (`दिए` / `दिले`) both spellings are listed. Where they
collide on a spelling (`बाकी`, `बिल`, `माल`) they mean the same thing and map
to the same marker, so the shared table is safe rather than merely convenient.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------- digits
#
# Merchants dictate amounts in whatever numeral set their keyboard produces.
# Python's \d already matches these, but int() of a mixed string does not.

_NUMERALS = {
    "devanagari": "०१२३४५६७८९",   # Hindi, Marathi
    "odia": "୦୧୨୩୪୫୬୭୮୯",
    "bengali": "০১২৩৪৫৬৭৮৯",
    "gujarati": "૦૧૨૩૪૫૬૭૮૯",
    "gurmukhi": "੦੧੨੩੪੫੬੭੮੯",
    "tamil": "௦௧௨௩௪௫௬௭௮௯",
    "telugu": "౦౧౨౩౪౫౬౭౮౯",
    "kannada": "೦೧೨೩೪೫೬೭೮೯",
    "malayalam": "൦൧൨൩൪൫൬൭൮൯",
}

DIGITS = str.maketrans(
    "".join(_NUMERALS.values()),
    "0123456789" * len(_NUMERALS),
)


# ------------------------------------------------------------ Hindi + Marathi
#
# One Devanagari table. Hindi spellings first in each group, Marathi after.

DEVANAGARI: dict[str, str] = {
    # --- money words -------------------------------------------------------
    "रुपये": "rupaye", "रुपए": "rupaye", "रूपये": "rupaye", "रुपया": "rupaye",
    "रुपयों": "rupaye", "रु": "rupaye", "पैसे": "rupaye", "पैसा": "rupaye",

    # --- khata / udhaar ----------------------------------------------------
    "बाकी": "baaki", "बाक़ी": "baaki", "शिल्लक": "baaki",
    "खाते": "khate", "खाता": "khata", "खात": "khate",
    "खात्यात": "khate", "खात्यावर": "khate",
    "उधार": "udhaar", "उधारी": "udhaar", "उसने": "udhaar", "उसनवार": "udhaar",
    "जमा": "jama",
    "वापस": "wapas", "परत": "wapas",
    "पेमेंट": "payment", "भुगतान": "payment",
    "चुकाया": "chukaya", "चुका": "chukaya", "फेडले": "chukaya",

    # --- verbs that mean money moved --------------------------------------
    "दिए": "diye", "दिये": "diye", "दिया": "diya", "दी": "di", "देदिए": "de diye",
    "दिले": "diye", "दिला": "diya", "देऊन": "diye",
    "भरा": "bhara", "भर": "bhar", "भरदिया": "bhar diya", "भरले": "bhara",
    "किया": "kiya", "किए": "kiye", "कर": "kar", "केले": "kiye", "केला": "kiya",
    "हुआ": "hua", "हुए": "hue", "झाले": "hua", "झाला": "hua",
    "लिया": "liya", "लिये": "liya", "घेतले": "liya", "घेतला": "liya",

    # --- future tense: a plan, not a payment ------------------------------
    "देना": "dena", "देनी": "deni", "करना": "karna", "मंगवाना": "mangwana",
    "लेना": "lena", "है": "hai", "हैं": "hain",
    "द्यायचे": "dena", "घ्यायचे": "lena", "करायचे": "karna",
    "आहे": "hai", "आहेत": "hain",

    # --- expense categories -----------------------------------------------
    "सप्लायर": "supplier", "सप्लाई": "supplier", "सप्लायर्स": "supplier",
    "होलसेल": "wholesale", "थोक": "wholesale", "ठोक": "wholesale",
    "माल": "maal", "स्टॉक": "stock", "गोदाम": "godown", "मंडी": "mandi",
    "बिजली": "bijli", "लाइट": "bijli", "बिल": "bill", "वीज": "bijli",
    "पानी": "pani", "पाणी": "pani", "गैस": "gas", "गॅस": "gas",
    "सिलेंडर": "cylinder",
    "किराया": "kiraya", "किराए": "kiraya", "भाड़ा": "bhada", "भाडे": "kiraya",
    "सैलरी": "salary", "तनख्वाह": "tankhwah", "पगार": "pagar",
    "नौकर": "naukar", "हेल्पर": "helper", "लड़के": "ladke", "मजदूरी": "labour",
    "नोकर": "naukar", "कामगार": "labour",
    "टेम्पो": "tempo", "टेंपो": "tempo", "ऑटो": "auto", "गाड़ी": "transport",
    "पेट्रोल": "petrol", "डीजल": "diesel", "ढुलाई": "transport",
    "खर्चा": "kharcha", "खर्च": "kharch", "खरीदा": "kharida", "ऑर्डर": "order",
    "खरेदी": "kharida", "विकत": "kharida",

    # --- grammar glue the patterns rely on --------------------------------
    #
    # Hindi writes its postpositions as separate words; Marathi and Odia glue
    # them onto the noun, so `सप्लायरला` is one token meaning "to the
    # supplier". Each maps to a SPACE-PREFIXED marker and the extra spaces are
    # collapsed afterwards -- otherwise the pair arrives as `supplierko` and
    # the `\bsupplier\b` matchers never fire.
    "को": " ko", "ने": " ne", "में": " mein", "से": " se", "का": " ka",
    "के": " ke", "की": " ki", "और": " aur", "आज": " aaj", "कल": " kal",
    "वाले": " wale", "वाला": " wale",
    "ला": " ko", "मध्ये": " mein", "मधून": " se", "चा": " ka", "ची": " ki",
    "चे": " ke", "च्या": " ka", "वर": " par",
    "आणि": " aur", "उद्या": " kal", "काल": " kal",

    # --- uncertainty markers, which must keep lowering confidence ---------
    "शायद": "shayad", "पता": "pata", "नहीं": "nahi", "लगता": "lagta",
    "कदाचित": "shayad", "माहित": "pata", "नाही": "nahi", "वाटते": "lagta",

    # --- chasing a debt ----------------------------------------------------
    "याद": "yaad", "दिलाओ": "dilao", "दिलाना": "dilana", "दिला दो": "dila do",
    "मांगो": "mango", "मांग": "mango", "याददिलाओ": "yaad dilao",
    "आठवण": "yaad", "आठव": "yaad", "मागा": "mango", "मागणी": "mango",

    # --- khata customer names ---------------------------------------------
    "सागर": "Sagar", "सुजित": "Sujit", "सुजीत": "Sujit", "राहुल": "Rahul",

    # --- stock words used by the shop-floor pipeline -----------------------
    "खत्म": "khatam", "खतम": "khatam", "नहीं है": "nahi hai",
    "चाहिए": "chahiye", "दो": "do", "एक": "ek",
    "संपले": "khatam", "संपला": "khatam", "नाही आहे": "nahi hai",
    "पाहिजे": "chahiye", "हवे": "chahiye", "दोन": "do",

    # --- spoken numbers ----------------------------------------------------
    # Nobody says "five thousand" as digits. Sarvam usually digitises these
    # for Hindi and Marathi, but not reliably and not at all for some
    # languages, so the words are mapped here and assembled further down.
    "तीन": "teen", "चार": "char", "पांच": "paanch", "पाँच": "paanch",
    "पाच": "paanch", "छह": "chhah", "छै": "chhah", "सहा": "chhah",
    "सात": "saat", "आठ": "aath", "नौ": "nau", "नऊ": "nau",
    "दस": "das", "दहा": "das",
    "सौ": "sau", "शंभर": "sau", "हजार": "hazaar", "हज़ार": "hazaar",
    "लाख": "lakh",
}


# ----------------------------------------------------------------------- Odia
#
# Odia has its own script, so nothing here can collide with the table above.

ODIA: dict[str, str] = {
    # --- money words -------------------------------------------------------
    "ଟଙ୍କା": "rupaye", "ଟଁକା": "rupaye", "ପଇସା": "rupaye",

    # --- khata / udhaar ----------------------------------------------------
    "ବାକି": "baaki", "ବକେୟା": "baaki",
    "ଖାତା": "khata", "ଖାତାରେ": "khate", "ଖାତାରୁ": "khate",
    "ଉଧାର": "udhaar", "ଧାର": "udhaar",
    "ଜମା": "jama",
    "ଫେରସ୍ତ": "wapas", "ଫେରାଇ": "wapas",
    "ପେମେଣ୍ଟ": "payment", "ଦେୟ": "payment",
    "ଶୁଝିଲା": "chukaya", "ଶୁଝି": "chukaya",

    # --- verbs that mean money moved --------------------------------------
    "ଦେଲି": "diye", "ଦେଲା": "diya", "ଦେଇଛି": "diye", "ଦେଇଥିଲି": "diye",
    "ନେଲା": "liya", "ନେଇଛି": "liya", "ନେଲି": "liya",
    "ଭରିଲି": "bhara", "ଭରିଛି": "bhara",
    "କଲା": "kiya", "କଲି": "kiya", "କରିଛି": "kiye",
    "ହେଲା": "hua", "ହୋଇଛି": "hua",

    # --- future tense: a plan, not a payment ------------------------------
    "ଦେବି": "dena", "ଦେବା": "dena", "ନେବି": "lena", "ନେବା": "lena",
    "କରିବି": "karna", "କରିବା": "karna", "ମଗାଇବି": "mangwana",
    "ଅଛି": "hai", "ଅଛନ୍ତି": "hain",

    # --- expense categories -----------------------------------------------
    "ସପ୍ଲାୟାର": "supplier", "ଯୋଗାଣକାରୀ": "supplier",
    "ପାଇକାରୀ": "wholesale", "ମାଲ": "maal", "ଷ୍ଟକ": "stock",
    "ଗୋଦାମ": "godown", "ମଣ୍ଡି": "mandi",
    "ବିଦ୍ୟୁତ": "bijli", "କରେଣ୍ଟ": "bijli", "ବିଲ": "bill",
    "ପାଣି": "pani", "ଗ୍ୟାସ": "gas", "ସିଲିଣ୍ଡର": "cylinder",
    "ଭଡ଼ା": "kiraya", "ଭଡା": "kiraya",
    "ଦରମା": "salary", "ମାଇନା": "salary",
    "ଚାକର": "naukar", "ହେଲପର": "helper", "ମଜୁରି": "labour",
    "ଟେମ୍ପୋ": "tempo", "ଅଟୋ": "auto", "ଗାଡ଼ି": "transport",
    "ପେଟ୍ରୋଲ": "petrol", "ଡିଜେଲ": "diesel", "ଗାଡିଭଡ଼ା": "transport",
    "ଖର୍ଚ୍ଚ": "kharch", "ଖର୍ଚ": "kharch",
    "କିଣିଲି": "kharida", "କିଣିଛି": "kharida", "ଅର୍ଡର": "order",

    # --- grammar glue the patterns rely on --------------------------------
    # Suffixed, not free-standing: see the note in the Devanagari table.
    "କୁ": " ko", "ରେ": " mein", "ରୁ": " se", "ର": " ka", "ଠାରୁ": " se",
    "ଏବଂ": " aur", "ଆଉ": " aur", "ଆଜି": " aaj", "କାଲି": " kal",

    # --- uncertainty markers, which must keep lowering confidence ---------
    "ହୁଏତ": "shayad", "ଜାଣିନି": "pata nahi", "ନାହିଁ": "nahi",
    "ଲାଗୁଛି": "lagta",

    # --- chasing a debt ----------------------------------------------------
    "ମନେ": "yaad", "ପକାଅ": "dilao", "ମନେ ପକାଅ": "yaad dilao",
    "ମାଗ": "mango", "ମାଗିବା": "mango",

    # --- khata customer names ---------------------------------------------
    "ସାଗର": "Sagar", "ସୁଜିତ": "Sujit", "ରାହୁଲ": "Rahul",

    # --- stock words used by the shop-floor pipeline -----------------------
    "ସରିଗଲା": "khatam", "ସରିଛି": "khatam", "ନାହିଁ ଅଛି": "nahi hai",
    "ଦରକାର": "chahiye", "ଲୋଡ଼ା": "chahiye",
    "ଗୋଟିଏ": "ek", "ଦୁଇଟି": "do",

    # --- spoken numbers ----------------------------------------------------
    # Sarvam digitises "पाच हजार" to 5000 for Marathi but returns Odia
    # amounts as words, so `ଦୁଇଶହ ଟଙ୍କା` arrived with no number in it at all
    # and the ledger saw a sentence about nothing.
    "ଏକ": "ek", "ଦୁଇ": "do", "ତିନି": "teen", "ଚାରି": "char",
    "ପାଞ୍ଚ": "paanch", "ଛଅ": "chhah", "ସାତ": "saat", "ଆଠ": "aath",
    "ନଅ": "nau", "ଦଶ": "das",
    "ଶହ": "sau", "ଶତ": "sau", "ହଜାର": "hazaar", "ଲକ୍ଷ": "lakh",
}


VOCABULARY: dict[str, str] = {**DEVANAGARI, **ODIA}

# The glue entries are exactly the ones written with a leading space above, so
# the split is derived rather than maintained as a second list that can drift.
GLUE = {word: marker for word, marker in VOCABULARY.items() if marker.startswith(" ")}
CONTENT = {word: marker for word, marker in VOCABULARY.items() if word not in GLUE}


def _alternation(words) -> str:
    """Longest first, so a compound never loses to one of its own parts."""
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


# Content words match anywhere: they are long enough to be unambiguous, and
# "बिजली का बिल" must not be beaten by "बिल" alone.
_CONTENT_PATTERN = re.compile(_alternation(CONTENT))

# Postpositions match ONLY at the end of a word. They are one or two syllables
# and turn up inside ordinary nouns: `दुकानात` ("in the shop") contains `का`,
# and without this guard it came out as `du ka naat`. Requiring a space, a
# punctuation mark or end-of-string after the match keeps the Marathi suffix
# in `सप्लायरला` while leaving `दुकानात` alone.
_GLUE_PATTERN = re.compile(rf"(?:{_alternation(GLUE)})(?=[\s,.!?;:]|$)")


def _apply_vocabulary(text: str) -> str:
    """Content words first: whatever they consume, the glue pass cannot split."""
    text = _CONTENT_PATTERN.sub(lambda m: CONTENT[m.group(0)], text)
    return _GLUE_PATTERN.sub(lambda m: GLUE[m.group(0)], text)


# ------------------------------------------------------------ spoken numbers
#
# Merchants dictate amounts, they do not spell them: "paanch hazaar", never
# "5000". Sarvam digitises this for some languages and not others -- the same
# sentence came back as `₹5000` in Marathi and as `ଦୁଇଶହ` in Odia -- so the
# words are assembled here and every language ends up with a number the amount
# parser can actually read.

_UNITS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
    "chhah": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
}
_SCALES = {"sau": 100, "hazaar": 1000, "lakh": 100_000}

# `\s*` and not `\s+`, because Odia writes the pair as one word: `ଦୁଇଶହ`
# romanises to `dosau` with nothing between the parts.
_SPOKEN_NUMBER = re.compile(
    rf"\b(?:({'|'.join(_UNITS)})\s*)?({'|'.join(_SCALES)})\b"
)

# A bare unit is only safe to convert when a currency word follows it. "das
# rupaye" is unambiguously ten rupees; a bare "do" is not, so it is left to
# the rule above. Odia needs this more than the others -- Sarvam digitises
# Hindi and Marathi amounts but returns `ଦଶ ଟଙ୍କା` as words.
_SPOKEN_UNIT_AMOUNT = re.compile(
    rf"\b({'|'.join(_UNITS)})\s+(?=(?:rupaye|rupay|rupees?|rs)\b)"
)

# Sentence enders. Sarvam returns them, and `diye।` is not a word.
_ENDERS = str.maketrans({"।": ".", "॥": "."})


def _assemble_numbers(text: str) -> str:
    """
    "do sau" -> "200", "paanch hazaar" -> "5000", "hazaar" -> "1000".

    Deliberately only multiplier phrases. A bare `do` is left alone, because
    "Maggi do" is a merchant asking for Maggi, not for two of anything, and
    turning it into "Maggi 2" would invent a quantity nobody said.
    """
    def replace(match: re.Match) -> str:
        unit, scale = match.group(1), match.group(2)
        return str((_UNITS[unit] if unit else 1) * _SCALES[scale])

    # Multipliers first, so "do sau rupaye" is already "200 rupaye" and the
    # bare-unit rule below cannot then re-read the "do" it has consumed.
    text = _SPOKEN_NUMBER.sub(replace, text)
    return _SPOKEN_UNIT_AMOUNT.sub(lambda m: f"{_UNITS[m.group(1)]} ", text)

# Ranges are checked in the order a mixed transcript is most likely to be in.
_SCRIPTS = {
    "devanagari": re.compile(r"[ऀ-ॿ]"),   # Hindi, Marathi
    "odia": re.compile(r"[଀-୿]"),
    "bengali": re.compile(r"[ঀ-৿]"),
    "gujarati": re.compile(r"[઀-૿]"),
    "gurmukhi": re.compile(r"[਀-੿]"),
    "tamil": re.compile(r"[஀-௿]"),
    "telugu": re.compile(r"[ఀ-౿]"),
    "kannada": re.compile(r"[ಀ-೿]"),
    "malayalam": re.compile(r"[ഀ-ൿ]"),
}

_INDIC = re.compile(r"[ऀ-෿]")


def detect_script(text: str) -> str | None:
    """Which Indic script this text is mostly in, or None for plain Latin."""
    for name, pattern in _SCRIPTS.items():
        if pattern.search(text):
            return name
    return None


def has_devanagari(text: str) -> bool:
    """Kept for callers that predate the other scripts."""
    return bool(_SCRIPTS["devanagari"].search(text))


def has_indic(text: str) -> bool:
    return bool(_INDIC.search(text))


def normalize(text: str) -> str:
    """
    Native script to the romanised form the matchers expect.

    Latin text passes through unchanged, so this is safe to call on every
    transcript regardless of which language the recogniser returned. A script
    with no vocabulary table yet (Tamil, Telugu, ...) still gets its numerals
    normalised, so an amount is recovered even when the words are not.
    """
    if not text:
        return text

    converted = text.translate(DIGITS).translate(_ENDERS)
    if not has_indic(converted):
        return _assemble_numbers(converted)

    converted = _assemble_numbers(_apply_vocabulary(converted))
    # Space-prefixed postposition markers leave gaps where Hindi already had
    # one; the matchers expect single spaces.
    return re.sub(r"\s{2,}", " ", converted).strip()


# ----------------------------------------------------------------- romanising
#
# `normalize` above only rewrites words this product branches on, which is the
# right rule for matching and the wrong one for display: a merchant reading
# their own books back should see "supplier ko 5000 diye", not a half-converted
# line with `सप्लायर` still in it.
#
# So display gets two passes. The curated table runs first, because it produces
# the exact spelling a shopkeeper would type ("supplier", "baaki", "rupaye").
# Whatever it did not cover is then transliterated syllable by syllable, which
# is approximate but readable -- and by then it is never a word any decision
# depends on, so an imperfect vowel costs nothing.

# Independent vowels, matras, consonants (inherent `a`), and the signs.
_DEVA_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    "ऍ": "e", "ऑ": "o", "ऎ": "e", "ऒ": "o",
}
_DEVA_MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॅ": "e", "ॉ": "o",
    "ॆ": "e", "ॊ": "o",
}
_DEVA_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "ळ": "l",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    # Nukta forms, spelled the way they are actually pronounced in a shop.
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
}
_DEVA_VIRAMA = "्"
_DEVA_SIGNS = {"ं": "n", "ँ": "n", "ः": "h", "ऽ": ""}

_ODIA_VOWELS = {
    "ଅ": "a", "ଆ": "aa", "ଇ": "i", "ଈ": "ee", "ଉ": "u", "ଊ": "oo",
    "ଋ": "ri", "ଏ": "e", "ଐ": "ai", "ଓ": "o", "ଔ": "au",
}
_ODIA_MATRAS = {
    "ା": "aa", "ି": "i", "ୀ": "ee", "ୁ": "u", "ୂ": "oo", "ୃ": "ri",
    "େ": "e", "ୈ": "ai", "ୋ": "o", "ୌ": "au",
}
_ODIA_CONSONANTS = {
    "କ": "k", "ଖ": "kh", "ଗ": "g", "ଘ": "gh", "ଙ": "ng",
    "ଚ": "ch", "ଛ": "chh", "ଜ": "j", "ଝ": "jh", "ଞ": "ny",
    "ଟ": "t", "ଠ": "th", "ଡ": "d", "ଢ": "dh", "ଣ": "n",
    "ତ": "t", "ଥ": "th", "ଦ": "d", "ଧ": "dh", "ନ": "n",
    "ପ": "p", "ଫ": "ph", "ବ": "b", "ଭ": "bh", "ମ": "m",
    "ଯ": "y", "ର": "r", "ଲ": "l", "ଳ": "l", "ୱ": "w",
    "ଶ": "sh", "ଷ": "sh", "ସ": "s", "ହ": "h",
    "ଡ଼": "d", "ଢ଼": "dh", "ୟ": "y",
}
_ODIA_VIRAMA = "୍"
_ODIA_SIGNS = {"ଂ": "n", "ଁ": "n", "ଃ": "h"}

def _transliterate(text: str, consonants, vowels, matras, signs, virama) -> str:
    """
    One syllabic script to Latin.

    Consonants carry an inherent `a` that a matra replaces and a virama
    suppresses. Word-final inherent `a` is dropped, which is what makes the
    output read as Hinglish (`ram`, `kharch`) rather than as Sanskrit
    (`rama`, `kharcha`).
    """
    out: list[str] = []
    index = 0
    length = len(text)
    max_len = max(len(c) for c in consonants)

    while index < length:
        # Longest consonant first, so a nukta pair is never split.
        matched = None
        for size in range(max_len, 0, -1):
            candidate = text[index : index + size]
            if candidate in consonants:
                matched = candidate
                break

        if matched is not None:
            index += len(matched)
            body = consonants[matched]

            # What follows decides whether the inherent vowel survives.
            following = text[index] if index < length else ""
            if following == virama:
                index += 1
                out.append(body)
            elif following in matras:
                index += 1
                out.append(body + matras[following])
            else:
                # Inherent `a`, unless this ends the word.
                at_word_end = index >= length or not _INDIC.match(text[index])
                out.append(body if at_word_end else body + "a")
            continue

        char = text[index]
        if char in vowels:
            out.append(vowels[char])
        elif char in matras:
            # A stray matra with no consonant: pronounce it as its vowel.
            out.append(matras[char])
        elif char in signs:
            out.append(signs[char])
        elif char == virama:
            pass
        else:
            out.append(char)
        index += 1

    return "".join(out)


def romanise(text: str) -> str:
    """
    Native script to readable Hinglish, for display and for the books.

    Latin text passes through untouched. Mixed text -- the normal case, since
    merchants say "UPI" and "Maggi" inside a Hindi sentence -- keeps its Latin
    runs exactly as spoken.

    Used for what a human reads. `normalize` is what the matchers read; the two
    agree on every word that matters because both start from the same table.
    """
    if not text:
        return text

    converted = text.translate(DIGITS).translate(_ENDERS)
    if not has_indic(converted):
        return _assemble_numbers(converted)

    # Curated spellings first, so decision words come out canonical.
    converted = _assemble_numbers(_apply_vocabulary(converted))

    if has_indic(converted):
        converted = _transliterate(
            converted, _DEVA_CONSONANTS, _DEVA_VOWELS, _DEVA_MATRAS,
            _DEVA_SIGNS, _DEVA_VIRAMA,
        )
        converted = _transliterate(
            converted, _ODIA_CONSONANTS, _ODIA_VOWELS, _ODIA_MATRAS,
            _ODIA_SIGNS, _ODIA_VIRAMA,
        )

    # Both passes leave gaps: the space-prefixed postposition markers, and
    # signs that romanise to nothing.
    return re.sub(r"\s{2,}", " ", converted).strip()
