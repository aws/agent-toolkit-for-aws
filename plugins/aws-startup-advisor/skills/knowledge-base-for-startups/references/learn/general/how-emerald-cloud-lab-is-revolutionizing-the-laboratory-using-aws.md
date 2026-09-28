---
source_url: https://aws.amazon.com/startups/learn/how-emerald-cloud-lab-is-revolutionizing-the-laboratory-using-aws
title: "How Emerald Cloud Lab is revolutionizing the laboratory using AWS"
---

## How Emerald Cloud Lab is revolutionizing the laboratory using AWS

> _Guest post by Ben Smith, VP of Engineering and Kevin J. Hou, Scientific Computing Engineer, Emerald Cloud Lab_

[Emerald Cloud Lab](https://www.emeraldcloudlab.com/) (ECL) provides access to a highly automated laboratory, equipped with over 200 unique pieces of scientific instrumentation, to any scientist with a computer and internet connection. Our wet lab – picture lab benches, hazardous chemicals, lab coats, and safety glasses – has diverse experimental capabilities with an emphasis on biotechnology, and supports a variety of enterprises including drug development, consumer products, and academic research.

Our platform enables scientists to design, execute, analyze and interpret their wet-lab experiments from anywhere in the world. Scientists simply ship their samples – anything from test tubes and cell-culture plates to commercial products – to the ECL and design experimental protocols through a software interface. These experiments are then run exactly as specified in the ECL workflows. Once the experiments are complete, scientists can analyze and interpret their data in the same software interface, and end up with a well-structured, easily navigable and complete record of the experimental execution and results. The ECL offers a myriad of benefits for scientists at universities, large pharmaceutical companies, and startups, such as:

_Reduced Capital Expenditures_ – The majority of the cost of biotech research typically lies in building and operating a laboratory. Individual instruments can take months to purchase and install, and the total cost of necessary equipment can be upwards of $10 million. Additionally, there are ongoing costs associated with ordering consumables, maintaining instruments, and performing qualifications. The Emerald Cloud Lab offers a year of access to a fully-managed laboratory with state-of-the-art instrumentation for less than the upfront cost of a single instrument. This substantially lowers the entry cost for startups wanting to conduct new and innovative research.

_Efficiency_ – Scientific progress is frequently bottle-necked by the sheer complexity of both experimental design and the operations required to execute them. Many scientists today spend 80% or more of their time managing the logistics of science (ordering materials, setting up instruments, waiting for instruments to run, etc.) instead of the science itself (forming hypotheses, designing experiments, analyzing results, etc.). The ECL allows scientists to focus on the science, leaving the logistics to the ECL, with the confidence that their experiments will be performed exactly as specified.

Additionally, the Emerald Cloud Lab uses a combination of laboratory automation and technology-driven operational efficiency to provide experimental throughput unattainable in a traditional lab. The cloud lab operates 24/7, and by taking advantage of these economies of scale, enhances scientific output while preserving low operating costs. All of this has translated into a 5-8x increase in the number of experiments a scientist can perform using the ECL as compared to a traditional laboratory.

_Reproducibility_ – Reproducing experimental results is one of the hallmark challenges of scientific research. Unreproducible results are typically caused by unreliable instrumentation, insufficiently documented protocols, and lost or incomplete data. The Emerald Cloud Lab addresses these issues using heavy integration with technology. For example, we use robotic liquid handlers for precise chemical preparation, and integrated software to ensure detailed measurements (e.g. temperature, weight, volume) are recorded into digital lab notebooks for every operation performed in the laboratory. This combination of automation, extensive monitoring, and procedural operations ensure no data is lost and all protocols are well-documented. Further, experimental protocols are abstracted in our Symbolic Lab Language (SLL), ensuring that repeating an experiment with identical settings is as simple as rerunning a few lines of code.

## Why AWS?

As our cloud lab expands to meet growing demand, we have faced a growing need for scalable, on-demand compute. This has been driven by the addition of instruments to the physical lab and by an increase in customer-driven research, where compute-intensive work such as simulations and image-analysis have been integrated into experimental workflows. Serverless, fully-managed AWS services were the perfect solution to address this growing need. The inherent scalability and pay-per-use cost structure of these services provide key advantages for our rapidly growing business, and have enabled us to seamlessly expand to meet growing computational demands.

To address the needs described above, we built Manifold, a microservices-based architecture that runs on AWS Fargate, which we use to provide on-demand asynchronous compute for both internal and external users of the Emerald Cloud Lab. Manifold enables users to run arbitrary, containerized code with full access to our laboratory APIs and database, i.e. with full access to the cloud lab and experimental data.

Since its full deployment in November 2021, Manifold has enabled full automation of routine lab scripts, such as inventory checks, instrument qualifications, and experiment scheduling. Whereas previously we had difficulty reliably running ~1,000 scripts/week with compute resources we had on premises, AWS has allowed us to seamlessly scale to ~5,000 scripts/week in the cloud. This has expanded the scope of automation in the lab, enabling routine tasks to run more frequently with fewer errors. Importantly, migration of our routine lab infrastructure to AWS has also enabled us to achieve 100% uptime on our remote compute services, allowing our computational architecture to remain functional through unpredictable events such as power outages and lab shutdowns.

## Manifold architecture

At a high level, Manifold consists of an API which allows users to define compute jobs, and backend AWS components which schedule and run these jobs. Our users interact with the service through desktop and browser apps, from which they make API calls (in the Symbolic Lab Language) to upload job definitions to our internal database, Constellation. To connect these job uploads to the rest of our components, we used [Amazon Kinesis](https://aws.amazon.com/kinesis) to stream changes from Constellation to the rest of our serverless architecture.

[Amazon DynamoDB](http://aws.amazon.com/dynamodb) is used to store internal state for the AWS Lambda functions.

Next, we use [AWS Lambda](http://aws.amazon.com/lambda) functions as a lightweight, scalable method to process the stream of database changes. These lambda functions, in conjunction with DynamoDB tables for storing internal state, are used to provision resources and schedule jobs. The lambda functions then pass compute jobs to our compute service, Fargate, using an SQS queue. Fargate is the keystone of the Manifold architecture – the ease of rapidly deploying containers with varying configurations and permissions has been critical for meeting the diverse computational needs for both our customers and internal developers.

The database-driven architecture described above not only allows for on-demand asynchronous computations, but also allows for jobs to run at scheduled times or in response to other changes in the database. Internally, we use the Manifold service to run routine jobs such as unit testing, sensor checks, and maintenance scripts. This same infrastructure is also used to provide customers with a service where they may submit long-running analyses such as simulations and video analysis to managed resources, with full access and integration with experimental data.

## Challenges

Deploying Manifold required us to overcome several challenges arising from the variable load and diverse nature of jobs submitted to the service. Fortunately, AWS provided us with crucial tools for addressing these problems.

In the cloud lab, jobs are often submitted in bursts – for example, after completion of a long experimental protocol, a large number of jobs may be submitted to process the newly generated experimental data. AWS Fargate enables us to effortlessly scale compute up and down to meet these fluctuating demands. More broadly, we have also taken advantage of the monitoring and management tools in AWS, such as [AWS CloudTrail](http://aws.amazon.com/cloudtrail) and [Amazon CloudWatch](http://aws.amazon.com/cloudwatch), to implement rate-limiting, which smooths out usage and enables us to set limits and priority on job submission on a per-user basis.

Following our initial test deployments, we determined that building robust logging into Manifold would be critical towards its success. To provide an optimal user experience, we sought to create tools for users to monitor and manage their Manifold jobs. To accomplish this, we set up infrastructure to selectively upload logging information, status updates, and potential errors from Fargate directly to our Constellation database. This has allowed us to provide users with curated dashboards showing job status, progress, usage limits, as well as error codes and traces for debugging user-submitted computations.

## Conclusion

AWS has allowed us to build Manifold, a unified service for remote computing which supports laboratory operations and provides computational services for our customers. The move toward cloud computing at the Emerald Cloud Lab has been obvious and inevitable – in many ways, the ECL is revolutionizing the traditional laboratory analogously to how AWS has revolutionized computing. The ease of use, reliability, and inherent scalability of AWS services has been a natural complement to our cloud lab model, enabling us to deliver an exceptional service to our current customers. Moreover, Manifold will be a key catalyst for future growth, enabling us to meet growing compute demand from customers conducting groundbreaking scientific research, and to support our operations as we increase the size and number of ECL facilities.

---

## Authors

### AWS Editorial Team

The AWS Startups Content Marketing Team collaborates with startups of all sizes and across all sectors to deliver exceptional content that educates, entertains, and inspires.

### Ben Smith

Ben Smith is the VP of Engineering at Emerald Cloud Lab, where he leads the Software Engineering, IT, and Scientific Computing teams.

### Kevin Hou

Kevin Hou is a Scientific Computing Engineer at Emerald Cloud Lab. His work ranges from designing distributed systems to building analysis software for high-throughput flow cytometry.
