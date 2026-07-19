# References

These papers were useful in designing the training programme this project supports.
They're collected here in case they're useful to you too, and so the choices behind the
code and the plan trace back to real sources rather than gym folklore.

Two groups: the formulas the code actually computes, and the wider training-science that
informed the plan, the targets, and the caveats.

Every citation was checked against the indexed record (PubMed / Crossref / Unpaywall)
before being listed; none is reconstructed from memory. Reach each paper through its DOI;
many are open access. No PDFs are shared here, only the links.

Not medical advice: these report what happened in studies, not what you should do. The
[README](README.md) has the full health-and-safety note.

## Methods the code computes

- **Heart-rate zones (Karvonen / heart-rate reserve).** Zones in `src/fitness/zones.py`
  use the %HRR method: target = RHR + %HRR × (HRmax − RHR).
  Karvonen MJ, Kentala E, Mustala O. "The effects of training on heart rate: a
  longitudinal study." *Annales Medicinae Experimentalis et Biologiae Fenniae*.
  1957;35(3):307–315. PMID 13470504.
- **Estimated 1RM (Epley).** The dashboard's e1RM curve uses Epley's formula,
  1RM = weight × (1 + reps / 30).
  Epley B. "Poundage Chart." *Boyd Epley Workout*. Lincoln, NE: Body Enterprises; 1985.
- **Polarised intensity distribution (Seiler).** The run polarisation target (mostly
  easy, a little hard) follows Seiler's endurance-distribution work.
  Seiler S. "What is best practice for training intensity and duration distribution in
  endurance athletes?" *International Journal of Sports Physiology and Performance*.
  2010;5(3):276–291. DOI: [10.1123/ijspp.5.3.276](https://doi.org/10.1123/ijspp.5.3.276).
  PMID 20861519.

## Further reading

Verified 2026-07-13, grouped by topic.

### Strength & hypertrophy

- Maeo S, Shan X, Otsuka S, Kanehisa H, Kawakami Y. "Triceps brachii hypertrophy is
  substantially greater after elbow extension training performed in the overhead versus
  neutral arm position." *European Journal of Sport Science*. 2023;23(7):1240–1250.
  DOI: [10.1080/17461391.2022.2100279](https://doi.org/10.1080/17461391.2022.2100279).
- Kassiano W, Costa B, Kunevaliki G, et al. "Greater gastrocnemius muscle hypertrophy
  after partial range of motion training performed at long muscle lengths." *Journal of
  Strength and Conditioning Research*. 2023;37(9):1746–1753.
  DOI: [10.1519/JSC.0000000000004460](https://doi.org/10.1519/JSC.0000000000004460).
- Wolf M, Androulakis-Korakakis P, Piñero A, et al. (incl. Nippard J, Swinton PA,
  Schoenfeld BJ). "Lengthened partial repetitions elicit similar muscular adaptations
  as full range of motion repetitions during resistance training in trained
  individuals." *PeerJ*. 2025;13:e18904.
  DOI: [10.7717/peerj.18904](https://doi.org/10.7717/peerj.18904). Finding: lengthened
  partials were *similar*, not superior, to full-ROM training in trained lifters (a
  null-result counterpoint to the lengthened-partial-advantage studies above).
- Refalo MC, Helms ER, Trexler ET, Hamilton DL, Fyfe JJ. "Influence of resistance
  training proximity-to-failure on skeletal muscle hypertrophy: a systematic review with
  meta-analysis." *Sports Medicine*. 2023;53(3):649–665.
  DOI: [10.1007/s40279-022-01784-y](https://doi.org/10.1007/s40279-022-01784-y). Small
  hypertrophy advantage for training closer to failure (effect size ~0.15–0.2).

### Tendon

- Cook JL, Purdam CR. "Is tendon pathology a continuum? A pathology model to explain the
  clinical presentation of load-induced tendinopathy." *British Journal of Sports
  Medicine*. 2009;43(6):409–416.
  DOI: [10.1136/bjsm.2008.051193](https://doi.org/10.1136/bjsm.2008.051193).
- Malliaras P, Barton CJ, Reeves ND, Langberg H. "Achilles and patellar tendinopathy
  loading programmes: a systematic review comparing clinical outcomes and identifying
  potential mechanisms for effectiveness." *Sports Medicine*. 2013;43(4):267–286.
  DOI: [10.1007/s40279-013-0019-z](https://doi.org/10.1007/s40279-013-0019-z).
- Kongsgaard M, Kovanen V, Aagaard P, et al. "Corticosteroid injections, eccentric
  decline squat training and heavy slow resistance training in patellar tendinopathy."
  *Scandinavian Journal of Medicine & Science in Sports*. 2009;19(6):790–802.
  DOI: [10.1111/j.1600-0838.2009.00949.x](https://doi.org/10.1111/j.1600-0838.2009.00949.x).
- Shaw G, Lee-Barthel A, Ross ML, Wang B, Baar K. "Vitamin C–enriched gelatin
  supplementation before intermittent activity augments collagen synthesis." *American
  Journal of Clinical Nutrition*. 2017;105(1):136–143.
  DOI: [10.3945/ajcn.116.138594](https://doi.org/10.3945/ajcn.116.138594).

### Hamstring & injury prevention

- van Dyk N, Behan FP, Whiteley R. "Including the Nordic hamstring exercise in injury
  prevention programmes halves the rate of hamstring injuries: a systematic review and
  meta-analysis of 8459 athletes." *British Journal of Sports Medicine*.
  2019;53(21):1362–1370.
  DOI: [10.1136/bjsports-2018-100045](https://doi.org/10.1136/bjsports-2018-100045).
- Petersen J, Thorborg K, Nielsen MB, Budtz-Jørgensen E, Hölmich P. "Preventive effect
  of eccentric training on acute hamstring injuries in men's soccer: a cluster-randomized
  controlled trial." *American Journal of Sports Medicine*. 2011;39(11):2296–2303.
  DOI: [10.1177/0363546511419277](https://doi.org/10.1177/0363546511419277).

### Endurance, protein & longevity

- Seiler S. (2010): polarised intensity distribution; see Methods above.
- Mandsager K, Harb S, Cremer P, Phelan D, Nissen SE, Jaber W. "Association of
  cardiorespiratory fitness with long-term mortality among adults undergoing exercise
  treadmill testing." *JAMA Network Open*. 2018;1(6):e183605.
  DOI: [10.1001/jamanetworkopen.2018.3605](https://doi.org/10.1001/jamanetworkopen.2018.3605).
- Celis-Morales CA, Welsh P, Lyall DM, et al. "Associations of grip strength with
  cardiovascular, respiratory, and cancer outcomes and all cause mortality: prospective
  cohort study of half a million UK Biobank participants." *BMJ*. 2018;361:k1651.
  DOI: [10.1136/bmj.k1651](https://doi.org/10.1136/bmj.k1651).
- Leong DP, Teo KK, Rangarajan S, et al. (PURE study investigators). "Prognostic value
  of grip strength: findings from the Prospective Urban Rural Epidemiology (PURE) study."
  *The Lancet*. 2015;386(9990):266–273.
  DOI: [10.1016/S0140-6736(14)62000-6](https://doi.org/10.1016/S0140-6736(14)62000-6).
- Morton RW, Murphy KT, McKellar SR, et al. "A systematic review, meta-analysis and
  meta-regression of the effect of protein supplementation on resistance training-induced
  gains in muscle mass and strength in healthy adults." *British Journal of Sports
  Medicine*. 2018;52(6):376–384.
  DOI: [10.1136/bjsports-2017-097608](https://doi.org/10.1136/bjsports-2017-097608).
- McKendry J, Currier BS, Lim C, Mcleod JC, Thomas ACQ, Phillips SM. "Nutritional
  supplements to support resistance exercise in countering the sarcopenia of aging."
  *Nutrients*. 2020;12(7):2057.
  DOI: [10.3390/nu12072057](https://doi.org/10.3390/nu12072057).
