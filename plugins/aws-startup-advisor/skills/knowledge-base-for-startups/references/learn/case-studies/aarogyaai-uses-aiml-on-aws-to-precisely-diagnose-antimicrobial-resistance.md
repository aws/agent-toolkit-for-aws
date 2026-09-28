---
source_url: https://aws.amazon.com/startups/learn/aarogyaai-uses-aiml-on-aws-to-precisely-diagnose-antimicrobial-resistance
title: "AarogyaAI uses AI/ML on AWS to precisely diagnose antimicrobial resistance"
---

## AarogyaAI uses AI/ML on AWS to precisely diagnose antimicrobial resistance

AarogyaAI, a healthcare and life sciences startup, is building with artificial intelligence and machine learning (AI/ML) on AWS.

---

Founders are familiar with the [startup dream](https://www.youtube.com/watch?v=rthxbzL1yIA). Built on an accumulation of life experiences, victories, defeats, data, iterations—and sometimes luck—this dream takes a startup on the journey from "[I've got this great idea](/startups/learn/evolutionary-architectures-series-part-1)" to proving what's possible.

[AarogyaAI](https://aarogya.ai/), a healthcare and life sciences (HCLS) startup in India, is built on a dream to "use the research that my co-founder and I did in academia and move the needle on human health," says chief executive officer (CEO) Dr. Praapti Jayaswal. AarogyaAI uses [artificial intelligence and machine learning](/startups/machine-learning/) (AI/ML) to rapidly diagnose drug resistance in patients caused by bacterial, fungal, and viral pathogens. This allows clinicians to make data-driven treatment decisions and prescribe drugs that effectively treat and increase health outcomes for patients.

Praapti and her co-founder, Avlokita Tiwari, the chief technology officer (CTO), began their friendship in 2012 as carpool buddies during the 30-mile drive from home to their lab at the Translational Health Science and Technology Institute in Faridabad, India. Praapti was working on her PhD in tuberculosis research and Avlokita was a junior research fellow.

Their friendship continued into 2019, when Avlokita told Praapti, "I'm looking for jobs." Praapti responded, "Don't look for jobs—come build this company together.'" Without hesitating, Avlokita simply answered "Yeah."

With that, AarogyaAI was founded. The company celebrated its 4th birthday in May of 2023 and today has nine clinical and commercial partnerships. They are running six infectious disease pipelines on the Amazon Web Services (AWS) cloud, as well as their repository of nearly 20,000 pathogen genomes.

## Proving what's possible in modern healthcare

"It frustrated us that people were dying of curable diseases. In 2018, [tuberculosis was the most lethal infectious disease](https://www.cdc.gov/globalhealth/newsroom/topics/tb/index.html#:~:text=TB%20is%20the%20leading%20infectious,1.5%20million%20lives%20each%20year.), even though there were 19 drugs to cure that bacterial infection," says Praapti. "We saw AI being used to make people richer, but not to make sick people healthier."

Praapti and Avlokita decided to change this by using AI to make precision diagnosis for antimicrobial resistance accessible at point of care. AarogyaAI allows clinicians to input the genomic sequencing of the patient's specimen into [AAICare](https://aarogya.ai/product/AAICare), an application built on AWS. Both Praapti and Avlokita believe that everyone can and should have access to effective treatment. "Our vision is making genomics available at point of care. Computing on AWS takes us one step closer to driving data-driven treatment decisions for positive outcomes at a population scale," explains Praapti.

AAICare quantitatively and qualitatively identifies all of the pathogens present, as well as the drug susceptibility of those pathogens. Additionally, AarogyaAI's ML models, which they build on [Amazon SageMaker](https://aws.amazon.com/sagemaker/), search for and predict mutations within the specimen that contribute to drug resistance.

> "Technology has evolved over the decades, but it's rarely being used in clinical practice," says Praapti. "We are changing that."

AarogyaAI is proving that proactive healthcare can become as normal as the reactive healthcare that is commonly practiced today. "We are demonstrating that the current genomics of pathogens and superbugs can predict what their future trends will be," says Praapti. "When a drug comes out, it's already 10 years too late. We need to apply technology to be able to create drugs preemptively, so that when a virus such as SARS-CoV-2 arises to wreak havoc across the globe—8 billion people—we're not at the mercy of that invisible thing."

To biologically and scientifically understand the evolutionary trends of pathogens, "Intelligent genomics is the crux of our work where we combine AI with genomics," explains Avlokita. "This helps in making treatment decisions today with the vision of extracting relevant information on pathogen evolution, thereby guiding public health policy-making for pandemic preparedness."

## Building their startup on AWS

Praapti and Avlokita decided that to build a secure, reliable, and scalable healthcare application, they would go all-in on AWS.

Aarogya AI uses AWS managed services like SageMaker, [Amazon Relational Database Service (Amazon RDS)](https://aws.amazon.com/rds/), and [Elastic Load Balancing](https://aws.amazon.com/elasticloadbalancing/) to complete tasks that would otherwise be cumbersome for engineering teams to set up and manage. This allows AarogyaAI to focus more on feature development of their product, instead of focusing on operating on a technology data center and the overhead that comes along with that.

> "The best part about using AWS is how seamless it all is," explains Avlokita. "It has been an amazing learning experience, to figure out all of the different features on AWS and how they can support our goals. We've been very happy with AWS."

To accelerate their startup's growth, AarogyaAI applied for and was accepted into [AWS ML Elevate](https://brands.yourstory.com/aws-ml-elevate-2022), an India-based program that helps AI/ML startups to showcase their innovations while providing mentorship and access to venture capital (VC) channels.

### Training and deploying machine learning models

ML models are key to AarogyaAI's ability to accurately analyze patient specimens and predict future trends. SageMaker is an AI/ML solution that helps their data science team to build, train, and fine-tune the ML models while providing complete control and visibility. "We rely on SageMaker to build our AI/ML models and deploy them," says Avlokita. AarogyaAI trains their SageMaker models on global and local genomic datasets available both publicly and generated on site, keeping the idea of translating research into real-world application in mind.

> "When our product lead joined the company, he had no experience on AWS. He knew data science and AI/ML algorithms, but he didn't know how to use AWS," says Avlokita. "SageMaker is so user friendly that he was able to jump right in and figure out how to build ML solutions."

Computations for the ML models run using [Amazon Elastic Compute Cloud (Amazon EC2)](https://aws.amazon.com/ec2/), which offers secure and reliable compute capacity on demand. For object storage, AarogyaAI uses [Amazon Simple Storage Service (Amazon S3)](https://aws.amazon.com/s3/).

### Optimizing cloud costs to reinvest in their business

As the next step in their product development, AarogyaAI wanted to make their AI algorithms more robust and able to analyze more pathogens. "We used AWS to run ML experiments. It was quick and efficient," says Avlokita. "We were very happy with the results. AWS allowed us to take away what we needed from these experiments and learn how to tailor our algorithms to include more pathogens."

As AarogyaAI experimented and learned how to expand their product, the amount of computation they used increased and affected their AWS bill. However, as members of [AWS Activate](https://aws.amazon.com/activate/)—a program that helps startups to build and scale—they were able to apply $100,000 in AWS credits towards their bill.

Additionally, "AWS in both India and the US were so generous in letting us know about different aspects of cost optimization. We were able to cut down our bill by 38% almost immediately," says Avlokita. "The way that AWS helped us to deal with cloud costs is something we're very happy with. Now, we can keep building."

## Looking ahead at AarogyaAI and healthcare on the cloud

Both Praapti and Avlokita are certain that the future of more equitable and effective healthcare is connected to technology. "Front and center, healthcare is going to rapidly become more tech-driven," says Avlokita. "It's important to us that we make products with the capability and scalability to adapt to new tech as it arrives."

For others that are building at this rapidly emerging intersection of healthcare and technology, Praapti advises, "The biggest thing I can share with other founders is: Don't wait for anything. Dive straight into the deep end." She explains, "It's never going to be the perfect time to reach out to someone or send that email or make that call or start that business or file that patent—whether you make the right call or the wrong call, you're going to come out net positive."

As the next steps in their startup journey, AarogyaAI plans to deploy their product more widely in the market, particularly in the US. "We've had super amazing support from AWS in India, Singapore, Asia Pacific, and in the US," says Praapti. "We are excited to begin to co-commercialize with AWS."

> "In 2012, when Avlokita and I used to carpool to the lab, we'd talk about our wildest dreams, like clinical trials becoming redundant using computational biology," laughs Praapti. "With AarogyaAI and AWS, our wildest dreams are slowly becoming a reality."

---

## About the Author

### Megan Crowley

Megan Crowley is a Senior Technical Writer on the Startup Content Team at AWS. With an earlier career as a high school English teacher, she is driven by a relentless enthusiasm for contributing to content that is equal parts educational and inspirational. Sharing startups' stories with the world is the most rewarding part of her role at AWS. In her spare time, Megan can be found woodworking, in the garden, and at antique markets.
