# The rollout image: the agent's world for one rollout.
#
# It holds the artifact, the train rows, and the in-box tool `rt` — and nothing
# else. The held-out splits are kept out twice over: `.dockerignore` removes
# them from the build context, and every COPY below names an explicit path so
# nothing arrives wholesale. The belt and the braces are both deliberate — a
# context filter is honoured by BuildKit and, under the legacy builder, only
# under the `.dockerignore` name, so the COPY discipline is what holds
# everywhere.
#
# Build from the experiment directory:
#   docker build -f Dockerfile -t synthetic-search:pinned .
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# The editable artifact. This is what the agent changes and what comes back.
COPY artifact/ /workspace/artifact/
COPY brief.md /workspace/BRIEF.md

# The measuring side lives outside /workspace: an agent that reads the scorer
# spends its turns on the scorer, and learns what it could game.
COPY src/ /opt/rt/src/
COPY tools/rt /usr/local/bin/rt

# Train rows only. val/ and test/ are excluded from the build context itself.
COPY state/corpus/train/ /opt/rt/corpus/train/
COPY state/corpus/manifest.json /opt/rt/corpus/manifest.json
COPY state/baseline_train.json /opt/rt/baseline_train.json

ENV PYTHONPATH=/opt/rt/src \
    SYNTH_STATE=/opt/rt \
    SYNTH_ARTIFACT=/workspace/artifact/rules.py

# The image commits its starting point, so `git status` in the box lists
# exactly what the rollout changed.
RUN git init -q /workspace && git -C /workspace add -A && \
    git -C /workspace -c user.email=rt@example.invalid -c user.name=rt commit -qm "rollout start"
