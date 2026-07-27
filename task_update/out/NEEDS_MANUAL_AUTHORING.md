# Rows needing manual authoring

2 of 161 Core rows resisted every automated pass. In
`final_hardened_20260727T105202Z.xlsx` their boundary sentence is neutralised
like every other row, but no new distinction was added, so they carry the same
difficulty as in `final.xlsx`. The other 159 rows each gained one distinction.

Both rows fail for the same underlying reason: the source bundle supports only
the four distinctions the sentence already makes. Across three passes the model
proposed a "new" distinction each time, but every proposal recombined words
already present in the existing sentence rather than naming a fresh confusion,
and the validator rejected it on those grounds.

To finish either row by hand, add one distinction a careful reader of the source
bundle could actually get wrong, then either write 2-3 distractors that are wrong
answers to the stated answer unit without restating the gold value, or leave
`optional_distractors` empty. An empty distractor list is accepted; a leaky one
is not.

### Core-batch7-task5-CORE-POL-40
- domain: policy
- existing distinctions: 4
- gold values: `0.293`, `0.0286`
- existing sentence: coefficient ratio vs percentage-point change; offset effect
  vs full elimination of loss; crop-yield adaptation vs general climate
  resilience; study example vs global average
- attempts: `yield-loss coefficient vs offset coefficient`, `implied ratio vs
  direct ratio`, `yield-loss coefficient vs adaptation ratio` — all rejected as
  recombinations of terms already in the sentence
- distractor problem: the answer is a pair of rounded coefficients, so every
  proposed distractor was one of the two gold figures

### Core-batch11-task3-BND-CORE-PAIR-013
- domain: economics
- existing distinctions: 4
- gold value: `Canada, Colombia, the Netherlands, New Zealand, Poland, and the
  United Kingdom`
- existing sentence: aggregate real GDP growth vs real GDP per capita;
  calendar-year 2023 vs forecast years; named country list vs regional examples;
  GDP-volume change vs nominal income or exchange-rate effects
- attempts: `real GDP growth vs real GNI growth`, rejected because GNI is already
  covered by the existing sentence. On the final pass the model declined the row
  outright, reporting that the source supports no fifth distinction without
  changing the research object or answer unit.
- distractor problem: the answer is a country list, so each proposed distractor
  repeated the full gold list with a different label attached
