#!/bin/sh
# raw pulls for scripts/cbb_intl.py: Barttorvik seasons (who played D-I) and Basketball-Reference international
# league totals. Basketball-Reference allows about 20 requests a minute.
C=scripts/.cache/cbb
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
mkdir -p $C/bt $C/intl
for y in $(seq 2008 2027); do
  [ -s $C/bt/adv$y.csv ] || curl -s -m 90 -A "$UA" "https://barttorvik.com/getadvstats.php?year=$y&csv=1" -o $C/bt/adv$y.csv
done
for lg in euroleague:2008 eurocup:2008 spain-liga-acb:2008 italy-basket-serie-a:2008 greek-basket-league:2008 france-lnb-pro-a:2008 \
          nbl-australia:2012 cba-china:2012 turkey-super-league:2021 israel-super-league:2021 aba-adriatic:2021 vtb-united:2021; do
  l=${lg%%:*}; a=${lg##*:}
  for y in $(seq $a 2027); do
    f=$C/intl/$l-$y.html
    if [ ! -s $f ] || [ $y -ge 2027 ]; then
      curl -s -m 60 -A "$UA" "https://www.basketball-reference.com/international/$l/${y}_totals.html" -o $f; sleep 3.5
      curl -s -m 60 -A "$UA" "https://www.basketball-reference.com/international/$l/${y}.html" -o $C/intl/$l-$y-teams.html; sleep 3.5
    fi
  done
done
