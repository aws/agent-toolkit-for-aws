## Flink Java Dependency Management

This document provides the complete Maven dependency configuration for Flink projects on Amazon Managed Service for Apache Flink. For new applications, default to Flink 2.2. For existing applications, use the user's current Flink version.

**For Kinesis-specific API usage and code examples**, see `kinesis-connector-guide.md`.

### Version-Specific Dependency Mapping

Not all connector versions are published for every Flink version. Use the correct combination from this table:

| Dependency | Flink 1.20 | Flink 2.2 | Notes |
|---|---|---|---|
| `flink.version` | `1.20.3` | `2.2.0` | Core Flink artifacts use this directly |
| `target.java.version` | `11` | `17` | Flink 2.x requires Java 17 minimum |
| `flink-connector-kafka` | `3.4.0-1.20` | `4.0.1-2.0` | Connector uses separate versioning scheme |
| `flink-connector-aws-kinesis-streams` | `5.1.0-1.20` | `6.0.0-2.0` | Connector uses separate versioning scheme |
| `flink-statebackend-rocksdb` | `1.20.3` (uses `flink.version`) | `2.2.0` (uses `flink.version`) | Available for both, can also use HashMap state backend via support case in MSF for apps that have small states that can fit in memory and benefit from lower latency state access |
| `aws-kinesisanalytics-runtime` | `1.2.0` | `1.2.0` | Same version for both |
| `aws-msk-iam-auth` | `2.3.5` | `2.3.5` | Version-agnostic |
| `maven-compiler-plugin` | `3.8.1` | `3.11.0` | Newer version recommended for Java 17 |

**Flink 2.2 additional notes:**

- `flink-statebackend-forst` is available as an alternative to `flink-statebackend-rocksdb` for disaggregated state management
- Logging uses `log4j-slf4j-impl` (same as 1.20; older Flink versions used `slf4j-log4j12`)
- See `flink-2x-migration.md` for API changes that affect application code (e.g., `open(OpenContext)`, `Duration` instead of `Time`, removed `SourceFunction`/`SinkFunction`)

### Example pom.xml for a Flink project

The example below defaults to Flink 2.2 properties (recommended for new applications). To use Flink 1.20 for existing applications, replace the properties block with the Flink 1.20 values from the table above.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xmlns="http://maven.apache.org/POM/4.0.0"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <!-- REPLACE: Use your application's package name -->
    <groupId>com.example</groupId>
    <!-- REPLACE: Use your application's artifact name -->
    <artifactId>my-flink-app</artifactId>
    <!-- Increment version as new changes are released -->
    <version>1.0</version>
    <packaging>jar</packaging>

    <!-- ============================================================
         Flink 2.2 properties (default for new applications)
         For Flink 1.20, replace with:
           target.java.version  = 11
           flink.version        = 1.20.3
           kafka.version        = 3.4.0-1.20
           kinesis-streams.version = 5.1.0-1.20
           maven.compiler.plugin.version = 3.8.1
         ============================================================ -->
    <properties>
        <!-- Build configs -->
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
        <buildDirectory>${project.basedir}/target</buildDirectory>
        <jar.finalName>${project.name}-${project.version}</jar.finalName>
        <target.java.version>17</target.java.version>
        <maven.compiler.source>${target.java.version}</maven.compiler.source>
        <maven.compiler.target>${target.java.version}</maven.compiler.target>

        <!-- Dependency versions -->
        <flink.version>2.2.0</flink.version>
        <kda.runtime.version>1.2.0</kda.runtime.version>
        <log4j.version>2.23.1</log4j.version>
        <!-- Not all kafka / flink version combinations are published on Maven -->
        <kafka.version>4.0.1-2.0</kafka.version>
        <msk-iam-auth.version>2.3.5</msk-iam-auth.version>
        <!-- Not all Kinesis / flink version combinations are published on Maven -->
        <kinesis-streams.version>6.0.0-2.0</kinesis-streams.version>
        <maven.compiler.plugin.version>3.11.0</maven.compiler.plugin.version>
    </properties>

    <!-- Java SDK for AWS required in general -->
    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>com.amazonaws</groupId>
                <artifactId>aws-java-sdk-bom</artifactId>
                <version>1.12.677</version>
                <type>pom</type>
                <scope>import</scope>
            </dependency>
        </dependencies>
    </dependencyManagement>

    <dependencies>
        <!-- Apache Flink dependencies required for most projects -->
        <dependency>
            <groupId>org.apache.flink</groupId>
            <artifactId>flink-clients</artifactId>
            <version>${flink.version}</version>
            <scope>provided</scope>
        </dependency>
        <dependency>
            <groupId>org.apache.flink</groupId>
            <artifactId>flink-streaming-java</artifactId>
            <version>${flink.version}</version>
            <scope>provided</scope>
        </dependency>
        <dependency>
            <groupId>org.apache.flink</groupId>
            <artifactId>flink-runtime-web</artifactId>
            <version>${flink.version}</version>
            <scope>provided</scope>
        </dependency>
        <dependency>
            <groupId>org.apache.flink</groupId>
            <artifactId>flink-connector-base</artifactId>
            <version>${flink.version}</version>
            <scope>provided</scope>
        </dependency>

        <!-- Flink Table Runtime — required when application code references
             internal Table Runtime types (InternalTypeInfo, RowDataSerializer,
             internal RowData converters). Commonly needed by Iceberg sinks
             that emit/consume RowData on a side output. Provided by MSF at
             runtime.

             Note: bridge != runtime. flink-table-api-java-bridge gives you
             the public Table API/SQL surface (DDL, TableEnvironment,
             DataStream<->Table conversion). flink-table-runtime gives you
             the internal data-structure types referenced by sinks and
             custom serializers. -->
        <dependency>
            <groupId>org.apache.flink</groupId>
            <artifactId>flink-table-runtime</artifactId>
            <version>${flink.version}</version>
            <scope>provided</scope>
        </dependency>

        <!-- Managed Service for Apache Flink Runtime required for all projects -->
        <dependency>
            <groupId>com.amazonaws</groupId>
            <artifactId>aws-kinesisanalytics-runtime</artifactId>
            <version>${kda.runtime.version}</version>
            <scope>provided</scope>
        </dependency>

        <!-- Kafka Connector required for Kafka source/sink projects -->
        <dependency>
            <groupId>org.apache.flink</groupId>
            <artifactId>flink-connector-kafka</artifactId>
            <version>${kafka.version}</version>
        </dependency>
        <!-- MSK IAM Auth required for Kafka projects using MSK IAM -->
        <dependency>
            <groupId>software.amazon.msk</groupId>
            <artifactId>aws-msk-iam-auth</artifactId>
            <version>${msk-iam-auth.version}</version>
        </dependency>

        <!-- Kinesis connector for Kinesis Streams source/sink projects -->
        <dependency>
            <groupId>org.apache.flink</groupId>
            <artifactId>flink-connector-aws-kinesis-streams</artifactId>
            <version>${kinesis-streams.version}</version>
        </dependency>


        <!-- RocksDB State Backend required for all projects -->
        <dependency>
            <groupId>org.apache.flink</groupId>
            <artifactId>flink-statebackend-rocksdb</artifactId>
            <version>${flink.version}</version>
        </dependency>

        <!-- JSON Processing required for JSON projects -->
        <dependency>
            <groupId>com.fasterxml.jackson.core</groupId>
            <artifactId>jackson-databind</artifactId>
            <version>2.15.2</version>
        </dependency>
        <dependency>
            <groupId>org.apache.flink</groupId>
            <artifactId>flink-json</artifactId>
            <version>${flink.version}</version>
        </dependency>


        <!-- Logging - generally required -->
        <dependency>
            <groupId>org.apache.logging.log4j</groupId>
            <artifactId>log4j-slf4j-impl</artifactId>
            <version>${log4j.version}</version>
        </dependency>
        <dependency>
            <groupId>org.apache.logging.log4j</groupId>
            <artifactId>log4j-api</artifactId>
            <version>${log4j.version}</version>
        </dependency>
        <dependency>
            <groupId>org.apache.logging.log4j</groupId>
            <artifactId>log4j-core</artifactId>
            <version>${log4j.version}</version>
        </dependency>
    </dependencies>


    <!-- Profile for local testing - includes provided dependencies -->
    <profiles>
        <profile>
            <id>local</id>
            <dependencies>
                <dependency>
                    <groupId>org.apache.flink</groupId>
                    <artifactId>flink-clients</artifactId>
                    <version>${flink.version}</version>
                    <scope>compile</scope>
                </dependency>
                <dependency>
                    <groupId>org.apache.flink</groupId>
                    <artifactId>flink-streaming-java</artifactId>
                    <version>${flink.version}</version>
                    <scope>compile</scope>
                </dependency>
                <dependency>
                    <groupId>org.apache.flink</groupId>
                    <artifactId>flink-runtime-web</artifactId>
                    <version>${flink.version}</version>
                    <scope>compile</scope>
                </dependency>
                <dependency>
                    <groupId>org.apache.flink</groupId>
                    <artifactId>flink-connector-base</artifactId>
                    <version>${flink.version}</version>
                    <scope>compile</scope>
                </dependency>

                <!-- Managed Service for Apache Flink Runtime -->
                <dependency>
                    <groupId>com.amazonaws</groupId>
                    <artifactId>aws-kinesisanalytics-runtime</artifactId>
                    <version>${kda.runtime.version}</version>
                    <scope>compile</scope>
                </dependency>
            </dependencies>
        </profile>
    </profiles>

    <!-- Most of the below is boilerplate for managing shaded JARs -->
    <build>
        <directory>${buildDirectory}</directory>
        <finalName>${jar.finalName}</finalName>
        <plugins>
            <!-- Java Compiler -->
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>${maven.compiler.plugin.version}</version>
                <configuration>
                    <source>${target.java.version}</source>
                    <target>${target.java.version}</target>
                </configuration>
            </plugin>
            <!-- Maven Shade Plugin -->
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-shade-plugin</artifactId>
                <version>3.2.1</version>
                <executions>
                    <execution>
                        <phase>package</phase>
                        <goals>
                            <goal>shade</goal>
                        </goals>
                        <configuration>
                            <artifactSet>
                                <excludes>
                                    <exclude>org.apache.flink:force-shading</exclude>
                                    <exclude>com.google.code.findbugs:jsr305</exclude>
                                </excludes>
                            </artifactSet>
                            <filters>
                                <filter>
                                    <artifact>*:*</artifact>
                                    <excludes>
                                        <exclude>META-INF/*.SF</exclude>
                                        <exclude>META-INF/*.DSA</exclude>
                                        <exclude>META-INF/*.RSA</exclude>
                                    </excludes>
                                </filter>
                            </filters>
                            <transformers>
                                <transformer
                                        implementation="org.apache.maven.plugins.shade.resource.ServicesResourceTransformer"/>
                                <transformer
                                        implementation="org.apache.maven.plugins.shade.resource.ManifestResourceTransformer">
                                    <!-- REPLACE: Use your application's fully qualified main class -->
                                    <mainClass>com.example.MyFlinkJob</mainClass>
                                </transformer>
                            </transformers>
                        </configuration>
                    </execution>
                </executions>
            </plugin>
        </plugins>
    </build>
</project>
```
