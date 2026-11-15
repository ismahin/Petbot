"""Incremental spoken clauses: short first audio, larger following phrases."""
import re
import time


class SpokenChunks:
    def __init__(self, first_words=6, following_words=14, first_wait=.45, split_commas=True,
                 sentence_mode=False, max_sentence_words=30,min_sentence_words=3,min_clause_words=3,
                 first_sentence_words=None):
        self.pending = ''
        self.first = True
        self.first_at = None
        self.first_words = first_words
        self.following_words = following_words
        self.first_wait = first_wait
        self.split_commas = split_commas
        self.sentence_mode = sentence_mode
        self.max_sentence_words = max_sentence_words
        self.min_sentence_words = min_sentence_words
        self.min_clause_words = min_clause_words
        self.first_sentence_words = first_sentence_words

    def feed(self, token, now=None):
        now = time.perf_counter() if now is None else now
        if self.first_at is None and token.strip():
            self.first_at = now
        self.pending += token
        result = []
        while self.pending:
            sentence_limit = self.first_sentence_words if self.first and self.first_sentence_words else self.max_sentence_words
            # Preserve punctuation for intonation; avoid splitting decimal numbers.
            match = re.search(r'[।!?\n]|(?<!\d)\.(?=\s|$)', self.pending)
            if self.sentence_mode:
                # Do not synthesize a one-word acknowledgment in isolation. Keep
                # it and its punctuation with the following sentence for prosody.
                matches = re.finditer(r'[।!?\n]|(?<!\d)\.(?=\s|$)', self.pending)
                match = next((m for m in matches if len(self.pending[:m.end()].split()) >= self.min_sentence_words),None)
            end = match.end() if match else None
            if self.sentence_mode and end and len(self.pending[:end].split())>sentence_limit:
                end=None
            clauses=re.finditer(r'[,;:](?=\s)', self.pending)
            clause=next((m for m in clauses if self.min_clause_words<=len(self.pending[:m.end()].split())<=sentence_limit),None)
            if self.split_commas and end is None and clause:
                end=clause.end()
            limit = self.first_words if self.first else self.following_words
            if self.sentence_mode:
                limit = sentence_limit
            boundaries = list(re.finditer(r'\s+', self.pending))
            waited = self.first_at is not None and now-self.first_at >= self.first_wait
            if end is None and len(boundaries) >= limit:
                if self.sentence_mode:
                    total_words=len(self.pending.split())
                    tail=total_words-limit
                    if 0<tail<self.min_sentence_words:
                        limit=max(self.min_sentence_words,total_words-self.min_sentence_words)
                end = boundaries[limit-1].start()
            elif end is None and not self.sentence_mode and self.first and waited and len(boundaries) >= 3:
                end = boundaries[-1].start()
            if end is None:
                break
            phrase, self.pending = self.pending[:end].strip(), self.pending[end:].lstrip()
            if re.search(r'\w', phrase):
                self.first = False
                result.append(phrase)
        return result

    def finish(self):
        phrase, self.pending = self.pending.strip(), ''
        return [phrase] if re.search(r'\w', phrase) else []
