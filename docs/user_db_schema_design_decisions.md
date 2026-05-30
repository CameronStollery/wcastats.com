# User data schema design decisions
At this stage, I'm not sure whether I will allow users to create private queries, or if saving a query will require it to be publicly available.

All tables use integer IDs for simplicity - I can see little advantage to using UUIDs for something of this scale. Integer IDs also allow queries to be accessed with simple, short URL paths.

The `user` table is mostly self-explanatory.

The `queries` table only stores _saved_ queries. When developing a query, a user will most likely make changes to their query and run it multiple times before deciding their query is complete and correct, and choosing to save it. All queries run on Athena, including all the intermediate queries run during development (some of which will fail to execute), are saved (query text + metadata) in Athena (for 45 days by default), and the results will be saved in S3. I need to decide how I want to manage these. The `queries` table stores the SQL text of queries that users have chosen to save, as well as a name and description given to them, and metadata (who created it and when).

The `query_runs` table stores the different runs of the queries in the `queries` table that have been done against _different versions of the WCA database_. For example, when a query is first created, a record in `query_runs` will be created and it will specify which version of the WCA database was used to generate the results. A few weeks later, if someone wants to see this query updated with the latest WCA resulsts, they can refresh the query, which will create a new query run with a new version of the WCA database. If the WCA database hasn't been updated since the last query run, then the query will be unavailable for refreshing, so a new query run for that query can't be created. Records in `query_runs` will contain the S3 address of their result sets. 

Since past query runs are available, I will probably (though not necessarily at first) allow users to view past runs of the query, i.e. see the results of running the query on a date in the past. That then leaves the possibility of allowing users to see what a query's results would be at a time in the past, when there hadn't already been the query run at this time. For example, someone want might want to see what the results of a query would be if it was run 6 months ago, but there is no existing query run for that query on the version of the WCA database from 6 months ago - either because the query had not been created, or because it had not been refreshed while that WCA DB version was active. If I was to make it so the user could generate the query results for this date, there are two ways I could do it:
1. Store every version of the WCA results export (and any additional tables) as Parquet files in a separate S3 folder, rather than just the current one, and allow users to run queries on past database versions. This is a seemingly simpler solution, but has issues:
    - More data to store (though with S3 pricing this is insignificant)
    - It only allows querying the past database versions for as long as this site has been running and storing past versions
    - Corrections on past data (retroactive DNFs etc) would not be taken into account - this could be a good or bad thing
    - It might be hard or impossible to automatically set up every database version with Glue Data Catalog, rather than just having one database based on a fixed set of tables
2. Allow users to query simulated past versions of the database by running the queries on views of the WCA DB tables that only have data up until a certain date. Issues:
    - Complex to implement (though probably doable, and doesn't need to be done straight away): the tables don't contain metadata for when records were created, so the only way to filter on dates would be by filtering on competitions that ended before a certain date, then filtering for only results (and scrambles) done at these eligible competitions, then filtering for only competitors with eligible results.
    - Wouldn't reflect structural changes such as adding events and formats - likely not an issue though.
    - Ranks tables wouldn't work, and would need to be recomputed.
    - Retroactive corrections would be taken into account - could be a good or bad thing.
    - Having query runs on simulated past data alongside query runs done on actual past data would be awkward.

As such, I will design my schema with the flexibility to handle either of these options:
- `query_runs` will have a column for the effective date of the run, i.e. the query is looking at results up to this date
- It will also have a column specifying which database update the run is querying, joining to a table that tracks all the database updates
- It will also have column to specify if this was a simulated query of past data.