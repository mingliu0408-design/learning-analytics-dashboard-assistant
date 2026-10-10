# Third-party notices and method attribution

No third-party package implementation, pretrained weight file, font, course-text corpus, paper PDF or student record is vendored in this repository. External libraries and model resources remain subject to their own terms; obtain them from their publishers. The absence of a new blanket licence is explained in LICENSING.md.

## Software and model dependencies

The offline analysis uses Python and NumPy 2.3.5. NumPy is installed separately; its distributed licence and notices remain in the installed package. Optional research implementation paths also use libraries such as PyTorch, sentence-transformers, Transformers, scikit-learn, pandas and the OpenAI SDK; exact component requirements and missing resources are recorded in the component documentation. These optional dependencies are not installed or run by the default reproduction entry point.

The embedding model identity is `sentence-transformers/all-mpnet-base-v2`, pinned in the source configurations to revision `e8c3b32edf5434bc2275fc9bab85f82640a19130`. The model card and weights must be obtained separately from the model publisher. Publishing this code does not grant redistribution rights to model files.

## Research methods and locally adapted instruments

RQ1's pair-feature head is a local adaptation; the source method uses a different feature construction and the local method freezes the encoder. RQ2 prototype differences, prescribed specialist-bit composition and the RAG-gate design are local implementations; the snapshot does not bundle or claim to reproduce third-party research repositories or their training procedures.

RQ3's eight criterion names and 1–5/NA instrument structure derive from the cited LAD dialogue instrument; the detailed behavioural anchors and frozen applicability are local operationalizations. The exported rubric retains attribution and local anchors. Transcribed third-party descriptive prose has been omitted where redistribution permission was not established; see rubric/ and the source map. No source paper or course document is included.

Source-file headers and local adaptation records are retained. The source-map records describe component identity and hash-preserving copies or specific adaptations; they are not licence grants. References mentioned in original code are attribution, not evidence that the full referenced algorithm was implemented.
