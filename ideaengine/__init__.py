"""Idea Engine - the half of HYPOLAB that decides WHAT is worth testing.

HYPOLAB (the `hypolab` package) tests ideas: bind -> lint -> simulate -> diagnose -> gate.
The Idea Engine plans the week, tracks the quarter's goals, and (in later phases) turns papers,
news and your own journal into new hypothesis cards in HYPOLAB's own format.

It only talks to HYPOLAB through public functions and two files:
  ~/.hypolab/journal.sqlite        written by HYPOLAB, read here
  ~/.hypolab/library/my_cards.yaml written here (approved cards), read by HYPOLAB
Its own state lives in ~/.hypolab/ideas.sqlite.
"""
__version__ = "0.1.0"
