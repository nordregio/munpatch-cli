# Known limitations

Two edge cases where the data or the algorithm don't fully cover reality.
Neither is a bug in the usual sense -- both are deliberate "leave it
visibly wrong/incomplete rather than guess silently" choices, documented
here so they don't need re-discovering.

## A table adopting a boundary change early

`extrapolate()` (both modes -- this isn't ratio-specific) only fills a gap
that's caused by crossing a *known* boundary (a `(code, year)` before a
code's `year_from` or after its `year_to`, per `changes.csv`). It has no
rule for a gap sitting *inside* a code's own still-valid range, and it
trusts `changes.csv`'s boundary years uniformly across every indicator. Both
assumptions broke, in a small way, for one specific merger in Gini.

`1901` Harstad + `1915` Bjarkøy merged into `1903` Harstad - Hárstták.
`changes.csv` (from the official KOM Masterliste) puts the boundary at
2012/2013: `1901`/`1915` valid through 2012, `1903` from 2013. Querying
each SSB table directly for those exact cells shows migration (13255) and
population (06913) both match that boundary exactly -- but Gini (09114)
already reports 2012 under `1903` (a real value, 0.21), with `1901`/`1915`
returning `null` for 2012. Gini's own table switched to the new code a full
year before the masterlist's official cutover date, for this one merger.

Since `extrapolate()` treats `changes.csv`'s year as authoritative for every
indicator, it expects `1901` to have a real 2012 value (year 2012 is *at*
its `year_to`, not after it, so no extrapolation rule fires) -- but Gini's
own table doesn't have one. The value is left as `NaN` rather than guessed
at, and this propagates to every later year for `1901` and `1915` (their
whole forward chain depends on that one missing value): 26 of `gini`'s
11,760 processed rows end up `NaN` for this reason. This is unrelated to
suppression (SSB does also suppress the coefficient for genuinely small
municipalities in some years -- `null` cells `fetch_ssb` drops alongside the
pre-existing zero-placeholder handling for count tables -- but that's not
what's happening for these two codes specifically). Left as `NaN`
deliberately (an honest "unknown", not a fabricated number); handling a
per-table boundary-year mismatch like this would need `changes.csv` to
allow a per-indicator override for this one merger, which hasn't been
built.

## Splits that can't be represented

`data/changes.csv` has been reconciled against the KOM Masterliste
(events from 2010 onward) and matches what `munpatch generate-changes`
produces from that file (see "Regenerating changes.csv from the
masterlist" in `README.md`). The full pipeline runs clean on the entire
2010+ history for both migration indicators.

Three codes are still only partially represented, on purpose rather than by
oversight -- the exact three `generate-changes` reports as conflicts: `0720`,
`1850`, and `5012` each split their territory across two or three different
merge targets in the same year, which the Recode/Split/Merge schema can only
represent as one target per code. Each currently has a row pointing at just
one of its real targets (the larger one, where there's a clear larger one)
so extrapolation doesn't crash or guess silently for the others sharing that
merge group -- it just doesn't capture that piece of the split. Modeling a
code that splits into a true merge (as opposed to a simple 1-to-N split into
fresh codes) isn't supported yet; would need a schema change, not a
changes.csv edit.

- **`0720` Stokke** (2016) -- split between `0704` Tønsberg and `0710`
  Sandefjord (merging with `0706` Sandefjord + `0719` Andebu). The
  masterlist's own remark quantifies this one: "et areal på 3 km2, med ca.
  2 200 personer overført fra Stokke til 0704 Tønsberg" (~2,200 people and
  3 km² went to Tønsberg), with "det meste av... Stokke" (most of Stokke)
  going to Sandefjord -- so `0710` is confirmed the larger share, not just
  an arbitrary pick. The row in `data/changes.csv` points at `0710`;
  Stokke's ~2,200-person contribution to Tønsberg isn't captured anywhere.
- **`1850` Tysfjord - Divtasvuodna** (2019) -- split between `1806` Narvik
  (merging with `1805` Narvik + `1854` Ballangen) and `1875` Hábmer -
  Hamarøy (merging with `1849` Hábmer - Hamarøy). The row points at `1806`;
  Tysfjord's contribution to Hamarøy is missing (and `1849`'s own row is
  correspondingly missing `1850` as a co-source).
- **`5012` Snillfjord** (2019) -- split three ways, into `5055` Heim
  (merging with `1571` Halsa + `5011` Hemne), `5056` Hitra (merging with
  `5013` Hitra), and `5059` Orkland (merging with `5016` Agdenes + `5023`
  Meldal + `5024` Orkdal). The row points only at `5055`; Snillfjord's
  contribution to Hitra and to Orkland is missing (so `5056`'s and
  `5059`'s own source lists are each undercounted by one).

Re-running `munpatch generate-changes` prints these same three codes with
their full competing-event details every time, so they don't need to be
re-derived from the masterlist by hand if this ever needs revisiting.
