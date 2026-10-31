"""Training and model modification: two trainers that really run, and the rest refused by name.

This machine has no GPU, no transformer weights and no fine-tuning library. The usual way to write
this milestone is to build a `train` command that shells out to something absent and prints a
plausible loss curve - which is exactly what M34 refused to do for speech. So the milestone is
split in two, along the line between *what is true here* and *what is not*:

**What really runs.** Two trainers, both dependency-free, both deterministic, both quick enough to
finish on a CPU in the time a command should take:

``ngram``
    a word-level n-gram language model with add-k smoothing. Trained on the ``train`` split, scored
    on every split with **perplexity** - a real number with a real definition, so a smaller one is
    better and a comparison means something.
``centroid``
    a nearest-centroid text classifier over hashed bag-of-words features. Labels come from the
    record's own ``label`` or from its parent directory, and the rule that produced them is written
    into the run's config rather than left to be guessed. Scored with accuracy per split.

Both write a JSON artifact through ``fs.write``, record its sha256, and register it as a version so
the artifact a metric came from cannot be silently replaced.

**What is refused.** ``lora``, ``qlora`` and ``full`` mean "fine-tune a transformer". The chain is
computed - the switch, the base model, the weights directory, the GPU, the library, the adapter -
and every missing link is reported in order, then stored on the job. The last link is always the
same: no adapter in this build can fine-tune anything, and a registered model is not enough.

Nothing here claims to train a transformer, to know what a GPU would cost, or to have measured a
model it did not train.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .service import TrainingService as TrainingService
from .constants import _WORD as _WORD, FEATURE_DIM as FEATURE_DIM
from .tokenization import tokenize as tokenize, _hash_feature as _hash_feature
from .ngram import NGramModel as NGramModel
from .centroid import CentroidModel as CentroidModel
from .algorithms import train_records as train_records
