"""Synthetic public-page cards. Not copied from a live marketplace."""

DONEDEAL_RESULTS = """
<html><head><link rel="next" href="?page=2"></head>
<body>
<nav><a href="/vans">Vans</a><a href="/sell">Sell your van</a></nav>
<article>
  <a href="/vans-for-sale/ford-transit-custom-2018/39112233">Ford Transit Custom 2018 L1 panel</a>
  <p>€12,950 + VAT</p>
  <p>84,000 km Dublin diesel manual</p>
</article>
<article>
  <a href="/vans-for-sale/ford-transit-custom-2019/39112234">Ford Transit Custom 2019</a>
  <p>Finance from €250 per month</p>
  <p>€15,500 inc VAT</p>
  <p>61,200 miles Cork</p>
</article>
<article>
  <a href="/vans-for-sale/ford-transit-custom-crew/39112235">Ford Transit Custom 2018 crew van</a>
  <p>€18,000 + VAT</p>
  <p>40,000 km Galway</p>
</article>
<article>
  <a href="/vans-for-sale/ford-transit-custom-2018/39112236">Ford Transit Custom 2018</a>
  <p>€1</p>
  <p>90,000 km Limerick</p>
</article>
</body></html>
"""

CARSIRELAND_RESULTS = """
<html><body>
<div>
  <a href="/used-cars/peugeot/partner/88221100">Peugeot Partner 2023 panel van</a>
  <span>€14,250 NO VAT</span>
  <span>42,000 km Waterford</span>
</div>
<a href="?page=2">Next</a>
</body></html>
"""

CARZONE_RESULTS = """
<html><body>
<script type="application/ld+json">
{"@type":"Vehicle","name":"Opel Combo 2020","url":"https://www.carzone.ie/used-cars/opel/combo/77331122","vehicleModelDate":"2020","mileageFromOdometer":{"value":"55000","unitCode":"KMT"},"offers":{"price":"11950","priceCurrency":"EUR"},"seller":{"name":"Harbour Vans Ltd","address":{"addressLocality":"Dublin","addressCountry":"Ireland"}}}
</script>
<div>
  <a href="https://www.carzone.ie/used-cars/opel/combo/77331122">Opel Combo 2020</a>
  <p>€11,950 including VAT</p>
  <p>55,000 km Dublin</p>
</div>
</body></html>
"""

DEALER_RESULTS = """
<html><body>
<script type="application/ld+json">
{"@type":"ItemList","itemListElement":[{"@type":"ListItem","item":{"@type":"Vehicle","name":"Ford Transit 2021 panel","url":"https://harbourvans.ie/stock/ford-transit-2021-44119920","vehicleModelDate":"2021","offers":{"price":"18900","priceCurrency":"EUR"},"mileageFromOdometer":{"value":"70000","unitCode":"KMT"}}}]}
</script>
</body></html>
"""

CHALLENGE_PAGE = """
<html><body><h1>Verify you are human</h1><p>Cloudflare captcha</p></body></html>
"""

PAGINATION_PAGE = """
<html><body>
<a href="/vans-for-sale/ford-transit-custom-2018/39110001">Ford Transit Custom 2018</a>
<p>€13,000 + VAT 80,000 km Dublin</p>
<a href="/vans?page=2">2</a>
</body></html>
"""
