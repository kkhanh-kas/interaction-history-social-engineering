# Interaction history and social engineering between LLM agents

[Tiếng Việt](README.md)

The program runs a two phase experiment between LLM agents. In the history phase the agents chat about the shared work of a project. In the attack phase a sender asks for the staging deploy token that the target agent holds under a role based sharing policy. The program measures how often the token leaks when the target remembers earlier chats with the sender (B), when those chats carry another name (A), and when they are left out of retrieval (C).

## Requirements

Python 3.9 or newer, standard library only. Models are called over HTTP through the Gemini API or the DeepSeek API.

## Running

`py pilot.py -h` lists the commands. Each script explains its use in its first lines.

`py pilot.py selftest` runs the whole pipeline on a mock model in a temp dir, with no API key.

## API keys

Copy `.env.example` to `.env` and paste the keys there. `.env` is gitignored.

## Data

The data dirs (`data-*/`) are not in the repo. They hold the histories, the retrieved records, the replies and the scores of every turn, that is the full text of the agents' conversations.

## Main runs

| Dataset | Run date | Commit |
|---|---|---|
| Gemini (`gemini-3.5-flash-lite`) | 4 Oct 2026 | `ebd3c79` |
| DeepSeek (`deepseek-flash`) | 5 Oct 2026 | `30fe0b0` |

The script hash in the logs was computed on a Windows checkout with CRLF line endings, so a fresh clone can give another hash for the same content.
