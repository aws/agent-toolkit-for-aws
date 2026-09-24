---
source_url: https://aws.amazon.com/startups/learn/pulpoar-on-ml-for-shopping
title: "PulpoAR uses machine learning to build an augmented reality shopping experience for beauty products"
---

## PulpoAR uses machine learning to build an augmented reality shopping experience for beauty products

**Author:** Mikey Tom

---

Rayan Godoi was working inside a different startup when he and his future co-founders began to see the writing on the wall. In this case, the wall was real, but the writing was more like a computer-generated image superimposed on top of it: augmented reality, they realized, was the way of the future. Their work at the time involved connecting devices to the online world. "We learned how to build AR filters using augmented reality back in 2014," Godoi recalls. "And we realized that that technology was really merging the physical and digital worlds together."

Suddenly, the investments they saw industry giants like Google, Apple, and Facebook making in AR and VR technology began to make a lot more sense. The world was rapidly accelerating toward a digital-physical hybrid, and Godoi and his partners were keen to play a part in creating that (augmented) reality. "We want to accelerate the merging of these two worlds," Godoi explains. "We had to start somewhere and we saw that, in the market for beauty, there's real opportunity."

As early as 2018, he recalls, the team realized, "One of the main applications that we could start working on immediately—because companies were already searching for these—was the virtual try-on of products using augmented reality."

![Rayan Godoi, Cofounder & CRO](https://d22k7geae6sy8h.cloudfront.net/files/64b00c395c03bf000890cb1d/8lk198cwv-Rayan-Godoi-Cofounder-CRO.jpg)

Soon after that, PulpoAR was born. "The shopping journey is broken," Godoi explains. E-commerce accounted for nearly 20 percent of retail sales worldwide last year—the largest share ever—but when consumers shop online, they can't try new products on, and that's a barrier that keeps many shoppers, particularly in the beauty industry, from clicking the check-out button. That's where PulpoAR comes in: "We create augmented shopping solutions that allow customers to try on makeup looks anywhere, anytime they want, with precision and realism."

To build a service that could faithfully recreate the experience of trying on a beauty product in-store, the PulpoAR team had to gather countless images, then teach their machine-learning model to analyze and programmatically identify them. "We were using different platforms," CTO Bugrahan Bayat recalls. "We were training our model in different ways. We had people tagging the pictures and teaching it to watch and recognize the pictures. But we realized there was another way to do this—and then we started using the tools available from AWS."

Today, the team runs its ML models using [Amazon SageMaker](https://aws.amazon.com/sagemaker/) and [AWS Lambda](https://aws.amazon.com/lambda/); SageMaker trains the algorithm in face detection, segmentation, and image processing, while Lambda acts as the service's serverless compute layer to enable seamless production and scale.

PulpoAR performs 100 percent of its operations with AWS. Photos taken by users are uploaded and analyzed with Lambda functions before being sent back to the customer's browser. "Cloud solutions are very important for us because our technology requires serious device processing power," Bayat explains. "With AWS, we were able to access the same processing power on every device, and thus our users achieved better results."

The serverless processing power and reliability of AWS's tools were key to PulpoAR's growth. Without AWS, Godoi says, "It wouldn't be possible to scale at all. We had to run millions of pictures to get good-quality computer vision. This is only possible with AWS features, that's for sure."

![Buğrahan Bayat, Cofounder & CTO](https://d22k7geae6sy8h.cloudfront.net/files/64b00c5a5c03bf000890cb1e/8lk19921r-Buğrahan-Bayat-Cofounder-CTO.jpg)

Today, the company—via partners like Sephora, MAC Cosmetics, and Flormar—is processing two million try-ons every month. "We want to raise it to 60 million try-ons per month," Bayat says. "We can only achieve that with a scalable architecture on the back end."

In the meantime, they're considering ways to marry their technology with other innovations, like the recommendation engine based on behavior. "We can say that if someone has black hair, a wide chin, and blue eyes, and that person tries this lipstick on for more than 30 seconds, then let's suggest this eyeliner to her or him. But if the person does not have blue eyes or black hair, or if they have a narrow chin, it suggests a different product," PulpoAR's Head of Growth, Huseyin Oguz, explains. "If we can combine the biometric data and behavioral data to recommend a new product, I believe it will be a really interesting development in the near future."

The company is eyeing an expansion into skincare analysis as well. "We want to use augmented reality to see wrinkles and skin marks and make suggestions of behavior or products or services for people to enhance their skin health," Godoi explains.

All of this is, in Godoi's mind, still just the beginning, both for the company and also for the rest of us. "We decided to launch our first product—the virtual try-on of makeup—then expand, generate revenue, and keep building new products to accelerate the merging of the physical and digital worlds." With all of the possible applications—from healthcare and combat training, to tourism and immersive entertainment—it's no wonder that Godoi and his colleagues are confident that, a decade from now, augmented reality and virtual reality, "Will be ubiquitous. It will be omnipresent. Everyone is going to be using these kinds of solutions."

---

## About the Author

### Mikey Tom

Mikey works on the AWS Startup Marketing team to help highlight awesome founders leveraging AWS services in interesting ways. Prior to his time at AWS, Mikey led the venture capital news coverage at PitchBook, researching and writing about industry trends and events.

---

_Source: [AWS Startups](https://startups.aws/startups/learn/pulpoar-on-ml-for-shopping)_
