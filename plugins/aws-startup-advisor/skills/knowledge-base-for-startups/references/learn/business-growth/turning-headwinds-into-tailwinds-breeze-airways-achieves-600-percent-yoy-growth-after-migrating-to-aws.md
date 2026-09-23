---
source_url: https://aws.amazon.com/startups/learn/turning-headwinds-into-tailwinds-breeze-airways-achieves-600-percent-yoy-growth-after-migrating-to-aws
title: "Turning headwinds into tailwinds: Breeze Airways achieves 600% YoY growth after migrating to AWS"
---

## Turning headwinds into tailwinds: Breeze Airways achieves 600% YoY growth after migrating to AWS

_By leveraging native AWS migration tools, Breeze was able to seamlessly migrate their entire infrastructure to AWS._

---

On December 17, 1903, Orville Wright—alongside his brother, Wilbur—completed the world's first flight of a powered airplane in Kitty Hawk, North Carolina. It [lasted only 12 seconds and covered just 120 feet](https://airandspace.si.edu/collection-objects/1903-wright-flyer/nasm_A19610048000#:~:text=After%20building%20and%20testing%20three,852%20ft)%20in%2059%20seconds)—but it changed everything. Fast-forward to today, approximately [130,000 commercial flights take place every 24 hours](https://www.iata.org/en/programs/safety/) and, according to the [International Air Transport Association (IATA)](https://www.iata.org/en/pressroom/2023-releases/2023-12-06-01/#:~:text=Total%20revenues%20in%202024%20are,4.5%20billion%20recorded%20in%202019), 4.7 billion people will travel by air in 2024. But while global air traffic is reaching historic highs, innovation across the industry has remained grounded for some time.

[Breeze Airways](https://www.flybreeze.com), together with Amazon Web Services (AWS), is changing that. Following unexpected outages and loss of service during its launch, Breeze Airways completed a seamless cloud-to-cloud migration from its previous provider to AWS. During the entire process, the airline collaborated closely with a dedicated team of AWS experts and was able to maintain a consistent level of service at all times. After modernizing its entire infrastructure, the migration was completed in the span of a week, and Breeze is now establishing itself as a major disruptor in the airline industry.

## Breaking with tradition

Founded by David Neeleman, co-founder of Morris Air, WestJet, JetBlue, and Azul Linhas Aereas, Breeze Airways brings affordable air travel to underserved markets across the US. "We saw that small and medium sized communities were losing air service. If you go back ten years, there's about 125 cities that have lost more than 25 percent of their air service" he explains.

Neeleman has previously referred to Breeze Airways as "a technology company that just happens to fly planes." Unlike its more traditional competitors, the company places technology at the forefront of everything it does, enabling its passengers—or _guests_—to enjoy a frictionless end-to-end travel experience every time they fly with Breeze. "This is a capital and labor-intensive business. The more that we can use technology to reduce our costs—and our fares—while making travel easier, the more people are going to want a fly," he explains.

"We want to take the friction out of travel" says Lukas Johnson, CCO at Breeze Airways. "We don't have a call center that's picking up the phone and taking reservations. Everything is digital. Designing that experience and then evolving that experience has been key to growing the company." He continues, "Airline technology is very old; there's a lot of old school programs, old school technologies, things that have been in place for decades. It was ripe for disruption and innovation."

Chris Shepherd, Principal Architect at Breeze Airways explains "It's an industry that traditionally hasn't moved quickly with technology, and I think a lot of airlines get stuck in a traditional way of thinking." While the Covid-19 pandemic rocked the industry, it also placed a spotlight on the need to digitize, but many established airlines were—and still are—reliant on outdated infrastructure.

## Breeze Airways takes to the runway

On May 27, 2021, Breeze Airways' inaugural flight took to the runway, traveling from Tampa International Airport to Charleston International Airport. At the time of launch, Breeze Airways unfortunately experienced repeated outages to its service. Shepherd explains, "we were on a fully managed hosting service and quickly found it was not going to be a good long-term fit. We weren't able to keep up with spikes in traffic, we weren't able to scale appropriately. We were doing a lot of promotions and a lot of new airport announcements and anytime you do that you're going to get a big influx of people."

During the outages, the Breeze Airways team had no failover in place and struggled to access the support needed to find a fix. "We had no control" recalls Shepherd. "We were just given a support portal to go to if we had issues, and that was down too. So, I was scouring for phone numbers looking through emails trying to find anybody to contact." In response to these issues, the Breeze Airways team made the decision to migrate its infrastructure to AWS.

## Turbulence-free cloud-to-cloud migration

AWS provided advice and best practices on service selection, future state mapping, and migration strategies to ensure uptime and avoid any further disruption. "The team we were given was awesome" says Shepherd, "it felt like they were basically a part of Breeze. They were excited to see Breeze succeed and even to fly Breeze themselves—it was refreshing to have that level of involvement." He continues, "we worked really closely with them during the initial planning and they gave us a good migration path. They also provided us with a consulting partner to work with."

Skye Hart, AWS Solutions Architecture Manager, explains, "the first step for any migration project is to assess the potential return on investment, as well as the associated risks of not migrating. If a business were to migrate, where would it be in six months? What would success look like? We work backwards from there."

"We started by whiteboarding out Breeze Airways' current infrastructure, their Kubernetes, their databases, and so on. It's all about understanding where a business is at in the present, recommending where they should be going, and mapping solutions towards that future state."

Hart continues, "we collaborated with the DevOps team to work out what they could do by themselves and where they would require support. We identified what migration tools would be needed, how testing and monitoring would be handled, and of course, what compliance and regulatory considerations we needed to adhere to."

## Maintaining altitude in the event of unexpected outages

The Breeze Airways DevOps team—which consisted of Shepherd and one other engineer—worked closely with AWS during deep dive sessions on disaster recovery processes, as well as regular progress meetings. "We brought in a disaster recovery specialist to provide guidance and build out a strategy that would avoid any outages during the migration" says Hart.

The AWS team employed best practices for disaster recovery based on the [AWS Well-Architected Framework](https://aws.amazon.com/architecture/well-architected/), which helps cloud architects build secure, high-performing, resilient, and efficient infrastructure for a variety of applications and workloads. Hart says: "It's our compass, our guide for best practices." Built around six pillars—[operational excellence, security, reliability, performance efficiency, cost optimization, and sustainability](https://aws.amazon.com/architecture/well-architected/?wa-lens-whitepapers.sort-by=item.additionalFields.sortDate&wa-lens-whitepapers.sort-order=desc&wa-guidance-whitepapers.sort-by=item.additionalFields.sortDate&wa-guidance-whitepapers.sort-order=desc)—the framework provides a consistent approach for customers and partners to evaluate architectures and implement scalable designs.

"We were laser-focused on the reliability pillar of the framework during the Breeze Airways migration," says Hart. "Our disaster recovery specialist helped the team define their recovery time and recovery point objectives, and advised them on what failover strategies to implement."

## Migrating at Mach speed

It was important that the most critical parts of Breeze Airway's infrastructure were migrated first to ensure a consistent level of service and avoid disruption. "We didn't want to just pick everything up and move it in one swoop." Over a six-month period, the team built out their new environment in a non-production setting. Speed was crucial. "The thing that really helped us move quickly was that we did everything as [infrastructure as code](https://aws.amazon.com/blogs/startups/should-startups-use-infrastructure-as-code-iac/)" says Shepherd.

Hart provides further detail: "Infrastructure as code is a really important tool for migration, and there's multiple options to choose from. For example, the [AWS Cloud Development Kit](https://aws.amazon.com/cdk/) and [AWS CloudFormation](https://aws.amazon.com/cloudformation/) are both powerful infrastructure as code solutions, and there are other options out there too. The Breeze team were familiar with [Terraform](https://docs.aws.amazon.com/whitepapers/latest/cicd_for_5g_networks_on_aws/terraform.html), so we went with that. It allowed them to essentially pack up their entire infrastructure and duplicate it. They could then continue to manage their current infrastructure while simultaneously building out their new one."

Shepherd explains, "we tried to remain agile and adapt quickly to any architecture changes that were needed." The AWS team recommended using managed services like [AWS Fargate](https://aws.amazon.com/fargate/), a serverless, pay-as-you-go compute engine that enabled the Breeze Airways DevOps team to spend less time on tasks such as server management and resource allocation. Hart explains, "it took away a lot of heavy lifting from the Breeze Airways team, enabling them to commit their focus to the migration itself."

Once their infrastructure had been completely codified and the team was happy with the results, they completed the migration within the span of a week. This involved promoting all of their services from the non-production setting into production. "It's pretty crazy for two engineers to do this while keeping an airline running—there were a lot of people that didn't think we could do it," explains Shepherd. "They thought we would need a large DevOps team but by utilizing some AWS managed services, we were able to do it much quicker than a lot of people had anticipated or experienced in the past."

"It's been really awesome post-migration; we've had no outages on AWS," Shepherd explains, "If you were to look at what our infrastructure looked like three years ago compared to now, it's wildly different due to the broad range of services available to us on AWS." With a reliable, secure, and stable cloud infrastructure in place, Breeze Airways was well and truly cleared for take off.

## App deployment reaches new heights post-migration

The Breeze Airways team follows a [continuous integration, continuous deployment (CI/CD) model](https://aws.amazon.com/solutions/app-development/ci-cd/) that, as Shepherd points out, "we couldn't have done on our old provider." He continues, "having that control over how we deploy our apps and how they get rolled out has really been key in us being able to deliver faster."

For example, Breeze Airways empowers its operations teams with a dedicated checklist application. Johnson explains: "We've got integrated data that's feeding pre-flight and post-flight checklists so that everybody can access the information they need. Our operations team is blown away given what they've previously experienced with other companies or older technologies." Breeze Airways has also recently launched a credit card with a well-known bank and, according to Shepherd, "it one of the quickest rollouts their team had ever been a part of."

## A first-class ticket to new growth

Since migrating to AWS, Breeze Airways has achieved 600% growth year-over-year (YoY), and looking ahead there's more to come. "We almost tripled in size last year," says Johnson, "and with AWS, it's just continuing to grow and scale. We just reached our first month of profitability in March, which is a really big milestone."

Neeleman explains, "the best thing that AWS gives companies like ourselves is reliability. Just being able to count on it, and not have to worry about things like maintenance, allows us to focus on what we do best—fly airplanes." He continues, "today, we serve about 170 routes across 56 cities—in eleven of those, we're the number one airline in terms of destinations served."

## Following a proven flight path for cloud-to-cloud migration

Breeze Airways' story shows the value cloud-to-cloud migrations can offer, yet common misconceptions can prevent businesses from taking the leap themselves. Hart explains: "I think one of the most common misconceptions is that the lights will go off, that there will be outages. Businesses are understandably anxious about data loss and are hesitant to migrate away from a service that might be delivering—or mostly delivering—on their immediate requirements."

She continues: "another misconception is that it takes a large team to complete a migration. A lot of startup founders may not realize that there's a whole ecosystem of solution architects, migration specialists, and qualified partners that can support them every step of the way."

By working with AWS, Breeze Airways had access to all the resources, expertise, and experience needed to confidently navigate a cloud-to-cloud migration and rapidly reach their target destination. By taking advantage of infrastructure as code, and AWS managed services, the team were able to act quickly and without any outages. This was also helped by working to a well-defined strategy based on proven best practices outlined in the AWS Well Architected Framework.

## Clear skies ahead

Wilbur Wright once referred to our skies as "[the infinite highway of the air](https://www.loc.gov/exhibits/dreamofflight/dream-dream.html)", and while we've come a long way since Kitty Hawk, our journey is far from over. Together with AWS, Breeze Airways is innovating in the cloud, and above them, empowering its guests and employees, and delivering frictionless, affordable air travel experiences to markets left underserved by more traditional competitors. [Learn more about the AWS Migration Acceleration Program (MAP)](https://aws.amazon.com/migration-acceleration-program/) and how your startup can accelerate your cloud migration with tools that reduce costs and automate and accelerate execution.

---

## Authors

### Skye Hart

Skye Hart is a Solutions Architecture Manager at Amazon Web Services based in Denver, Colorado. With a passion for innovation and expertise in cloud computing, her team is dedicated to helping startups build and launch scalable solutions on AWS.

### Chris Shepherd

Chris Shepherd is the Principal Technical Architect at Breeze Airways with over 20 years experience in technology roles such as engineering, devops, and architecture. He is a technology generalist that thrives at providing forward thinking solutions in a fast-paced environments.

### Lukas Johnson

Lukas Johnson is the Chief Commercial Officer at Breeze Airways with over 14 years in senior leadership positions at Allegiant and Canada Jetlines. He took the Allegiant network from 150 to over 400 routes, growing revenue over 200%.

### David Neeleman

David Neeleman is the Founder and Chief Executive Officer of Breeze Airways. Now on his 5th airline, he is a true serial entrepreneur and pioneer in the aviation industry.

---

_Source: [AWS Startups](https://startups.aws/startups/learn/turning-headwinds-into-tailwinds-breeze-airways-achieves-600-percent-yoy-growth-after-migrating-to-aws)_
