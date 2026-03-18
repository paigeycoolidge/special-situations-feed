from datetime import date

JEFFERSON_QUOTES = [
    "The man who reads nothing at all is better educated than the man who reads nothing but newspapers.",
    "I cannot live without books.",
    "Never spend your money before you have earned it.",
    "In matters of style, swim with the current; in matters of principle, stand like a rock.",
    "The price of liberty is eternal vigilance.",
    "I find that the harder I work, the more luck I seem to have.",
    "Do you want to know who you are? Don't ask. Act! Action will delineate and define you.",
    "Nothing can stop the man with the right mental attitude from achieving his goal.",
    "Honesty is the first chapter in the book of wisdom.",
    "The most valuable of all talents is that of never using two words when one will do.",
    "We hold these truths to be self-evident: that all men are created equal.",
    "I like the dreams of the future better than the history of the past.",
    "When you reach the end of your rope, tie a knot in it and hang on.",
    "Determine never to be idle. No person will have occasion to complain of the want of time who never loses any.",
    "He who knows best knows how little he knows.",
    "Educate and inform the whole mass of the people. They are the only sure reliance for the preservation of our liberty.",
    "The earth belongs to the living, not to the dead.",
    "I would rather be exposed to the inconveniences attending too much liberty than those attending too small a degree of it.",
    "The God who gave us life gave us liberty at the same time.",
    "No duty the Executive had to perform was so trying as to put the right man in the right place.",
    "It is always better to have no ideas than false ones.",
    "One man with courage is a majority.",
    "The care of human life and happiness, and not their destruction, is the first and only object of good government.",
    "Were it left to me to decide whether we should have a government without newspapers, or newspapers without a government, I should not hesitate a moment to prefer the latter.",
    "Question with boldness even the existence of a God; because, if there be one, he must more approve of the homage of reason, than that of blindfolded fear.",
    "Whenever you do a thing, act as if all the world were watching.",
    "The most fortunate of us, in our journey through life, frequently meet with calamities and misfortunes which may greatly afflict us.",
    "Nothing gives one person so much advantage over another as to remain always cool and unruffled under all circumstances.",
    "Our greatest happiness does not depend on the condition of life in which chance has placed us, but is always the result of a good conscience, good health, occupation, and freedom in all just pursuits.",
    "I hope our wisdom will grow with our power, and teach us that the less we use our power the greater it will be.",
]


def get_daily_quote():
    """Return (quote, index) for today, rotating through all 30 quotes by day of year."""
    day_of_year = date.today().timetuple().tm_yday
    idx = (day_of_year - 1) % len(JEFFERSON_QUOTES)
    return JEFFERSON_QUOTES[idx], idx
