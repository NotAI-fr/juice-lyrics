# Metadata repair safety design

The audit/preview UI still has no Apply action. The backend transaction in
`services/metadata_repair.py` now implements the safety foundation below for
MP3, FLAC, and M4A, but it is deliberately not exposed to normal users until a
separate field-selection/confirmation acceptance pass is complete.

## Evidence and user decision

- Repairs require a current, confirmed catalogue identity. Unknown tracks never
  receive guessed values.
- Missing local fields backed by explicit catalogue data may be marked
  **Confident**. A difference from an existing non-empty value is **Review** and
  must be selected explicitly by the user.
- Recording/version markers remain meaningful. Live, remix, session, extended,
  TV mix, numbered versions, and similar distinctions must not be flattened.
- The apply plan must pin the audio path, pre-edit whole-file SHA-256 and
  filesystem fingerprint, catalogue ID, selected fields, identity provenance,
  and state-file signature shown in the preview.

## Format-specific writes

Only the selected common text fields should change:

- MP3: `TIT2`, `TPE1`, `TALB`, and `TRCK` ID3 frames.
- FLAC: `TITLE`, `ARTIST`, `ALBUM`, and `TRACKNUMBER` Vorbis comments.
- M4A: `©nam`, `©ART`, `©alb`, and `trkn` MP4 atoms.

The writer must preserve the encoded audio stream and every unrelated tag. In
particular it must round-trip MP3 USLT/SYLT/APIC, FLAC `LYRICS` and pictures,
M4A `©lyr` and cover art, custom/free-form tags, and unknown metadata. Adjacent
`.lrc` files are outside the transaction and must remain byte-identical.

## Transaction and recovery

1. Re-read state and the source fingerprint/hash; abort if either differs from
   the preview.
2. Create the normal complete audio backup before any original-file mutation.
3. Copy to a same-filesystem temporary file, update only approved fields, and
   save/fsync the temporary copy.
4. Re-open the temporary copy and verify the requested tags, media readability,
   audio-stream identity where measurable, embedded lyrics, artwork, and all
   unrelated tags.
5. Recheck source and state conflict guards, then atomically replace the audio.
6. Compute and verify the new whole-file SHA-256/fingerprint and atomically bind
   state to that result. If this final state update conflicts or fails, restore
   and verify the backed-up original rather than leaving state and media split.
7. Keep the backup under the existing newest-10-valid retention policy. Clean
   abandoned temporary files safely after interruption; never treat them as
   library audio.

No state should record a post-edit hash until the replacement has been verified.
No success should be reported until both media and state agree.

The implemented service requires an explicit subset of previewed fields and an
explicit `confirmed=True` execution gate. It pins the original state bytes,
whole-file hash/fingerprint, catalogue ID, unrelated tag snapshot, encoded
media payload hash, and adjacent-sidecar signature. It creates and manifests a
normal backup before editing a same-filesystem temporary copy. The copy is
reopened and verified before atomic replacement; state failure rolls the audio
back. Tests also cover interruptions immediately after media/state replacement.

## Manual identity locks

A controlled metadata edit necessarily changes the whole-file SHA-256. A valid
manual identity lock may be rebound to the new hash only when all of these are
true:

- the pre-edit hash/fingerprint still matches the lock and preview;
- the catalogue ID is unchanged;
- only explicitly approved metadata fields changed;
- post-write media/tag/preservation verification passed; and
- the atomic state update succeeded without a conflict.

Any unexpected file change, identity change, verification failure, interruption,
or state conflict must preserve/restore the original binding rather than weaken
the normal changed-file safety rules.

## Remaining UI integration

- Add an explicit per-field selector to the existing preview. Review fields
  must never be preselected merely because catalogue text differs.
- Add a cancel-first destructive confirmation summarizing the selected fields,
  path, and backup behavior.
- Run the backend transaction in a worker, refresh the Library snapshot after
  success, and provide the generated backup path on success/failure.
- Complete manual acceptance with representative real-world copies before
  enabling Apply for normal libraries.
