# Test fixtures

## `jfk.flac`

Provenance: `tests/jfk.flac` from **openai/whisper** at tag `v20250625`
(MIT-licensed repository; the recording itself is a public-domain excerpt of a
1961 presidential address). Copied byte-for-byte:

```
$ sha256sum fixtures/jfk.flac
$ sha256sum /tmp/wsr/whisper-20250625/tests/jfk.flac
```

It is the fixture the candy's `whisper-transcribes-fixture` check decodes: the
check asserts the served endpoint returns the words **"fellow Americans"**, which
is a property of the audio, not of the model under test — any checkpoint from
`tiny` upward transcribes this clip correctly, so the assertion proves the
SERVICE (decode → transcribe → JSON `text`), not a particular model.

Why a committed clip rather than one generated in the bed: a synthesized fixture
would add a second engine (TTS) to the R10 story, and the point of this check is
that the *served HTTP surface* works, not that two engines agree.
