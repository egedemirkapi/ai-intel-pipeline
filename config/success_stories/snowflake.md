# Snowflake — separated storage from compute and killed Oracle DWH

## Founding insight
Benoit Dageville and the founding team saw that traditional data warehouses (Oracle, Teradata) coupled storage and compute on the same hardware — meaning if you needed to scale one, you paid for the other. The contrarian bet: redesign the warehouse from scratch on the cloud, with storage (S3) and compute (elastic) decoupled, so customers paid only for what they used. One architectural choice would invalidate every incumbent's economics.

## Initial wedge
Data teams at digitally-native companies (Adobe, Capital One, DoorDash) who had outgrown their Redshift / Hadoop setups but couldn't migrate to Oracle pricing. They had budget *and* the engineering talent to evaluate a new architecture on its merits — exactly the buyers who would adopt based on the technical story rather than the brand.

## Timing call
2014-2015 (founded 2012, GA 2015). Cloud-native everything was hitting mainstream enterprise, but data warehouses had remained on-prem. The window between "cloud is enterprise-acceptable" and "incumbents migrate" was the asymmetric opportunity. Three years earlier no enterprise would have moved data to S3; three years later AWS/GCP would have shipped competing decoupled warehouses.

## Distribution mechanism
Data-engineering word-of-mouth + analyst pressure (Gartner). Once a few brand-name data teams said "we cut our warehouse spend 70%," the procurement floodgates opened. Heavy enterprise sales motion eventually, but founded on a product story competitors couldn't tell. Data Cloud (the marketplace where customers share datasets) layered network effects on top.

## 10× moment
*Elastic compute, per-second pricing*. Customers ran a 1000-node query for 10 minutes and paid for 10 minutes; competitors made them provision the cluster for the week. Cost-per-query was 10× lower on bursty workloads — the workload pattern most analytics actually has.

## Default-status moat
By 2020 IPO ($120B peak market cap), Snowflake was the default cloud warehouse evaluation alongside BigQuery. The Data Cloud network effect — your business partners and vendors all have Snowflake too, so shared datasets get easier — compounded the structural choice into a 10-year platform. One architectural insight, layered with a marketplace, became a 5,000-person company.
