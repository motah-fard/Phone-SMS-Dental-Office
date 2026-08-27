# Showing "DENTAL ARTS PRACTICE" instead of a raw phone number

This isn't something the code controls — it's a carrier-level feature
on whichever phone number you provision through Telnyx. Two real
options, with a character-limit catch worth knowing up front:

## Option 1: CNAM (Caller ID Name)

The older, simpler system. Telnyx registers a name for your number in
a shared industry database; the *receiving* carrier looks it up and
displays it.

- **Cost:** ~$0.40/month per number.
- **Catch:** capped at 15 characters. "DENTAL ARTS PRACTICE" is 20
  characters — it would show truncated, e.g. "DENTAL ARTS PRA" or
  a manually chosen abbreviation like "DENTAL ARTS DR" or "DR NAZARI
  DENTAL". Worth deciding the exact 15-character string now rather
  than letting a truncation happen automatically.
- **Catch:** CNAM databases are notoriously outdated/inconsistent, and
  not every carrier or phone even displays it — some Android/iOS
  combinations show it reliably, others show nothing or "Unknown."
  There's no verification behind it either (which is also why it's
  cheap and fast to set up).

## Option 2: Branded Calling

The modern, verified system — built on STIR/SHAKEN call authentication.
Shows a full business name (not truncated) and can include a logo and a
stated reason for the call on supporting phones.

- Requires registering the practice as a verified business with
  Telnyx (a "Display Identity Record") — they verify business identity
  and phone number ownership before it goes live.
- More setup lead time than CNAM, and Telnyx doesn't publish flat
  pricing for it — needs a direct quote from their sales team.
- Not universally supported yet either — depends on the receiving
  carrier and phone having STIR/SHAKEN branded-call support, though
  this is becoming more common.

## Recommendation

Given the cost-sensitivity discussed earlier, start with CNAM (cheap,
fast) using a deliberately chosen 15-character name rather than letting
"DENTAL ARTS PRACTICE" get cut off awkwardly, and evaluate Branded
Calling later once real call volume shows it's worth the extra setup
and cost. Neither guarantees every caller sees a name instead of a raw
number — that's a real limitation of how phone networks work today, not
something to promise the practice as 100% guaranteed.

Sources: [Telnyx CNAM vs Outbound Caller ID](https://support.telnyx.com/en/articles/1130720-caller-id-outbound-vs-cnam), [Telnyx Branded Calling](https://telnyx.com/products/branded-calling)
