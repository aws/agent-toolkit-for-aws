---
source_url: https://aws.amazon.com/startups/learn/through-aws-impact-accelerator-eyegage-formed-crucial-connection-to-prepare-machine-learning-demo
title: "How Eyegage scaled their life-saving app via Impact Accelerator partnership"
---

## How Eyegage scaled their life-saving app via Impact Accelerator partnership

_To celebrate Black History Month, AWS Startups is featuring posts throughout February highlighting the contributions of Black builders and leaders in tech. Above all, these individuals inspire, empower, and encourage others—especially those historically underrepresented in tech—to [prove what's possible](https://aws.amazon.com/startups/prove-whats-possible/)._

Dr. LaVonda Brown, founder and CEO of [Eyegage](http://eyegage.com/), whose expertise lies in artificial intelligence (AI) and eye-analysis technologies, developed a robotic engagement model based on user eye gaze and pupil size (dilation and constriction).

This published, patented, and licensed model has been applied to several use cases, including math education and physical therapy to improve outcomes. Her work has also led to using eye tracking as a viable biomarker for mild cognitive impairment and early-onset Alzheimer's Disease.

LaVonda used her expertise to launch EyeGage, a mobile app that applies eye-analysis techniques to evaluate whether individuals are under the influence of drugs and alcohol to help prevent fatal accidents.

Eyegage planned to go to market with their mobile application in December 2022, but they had to deliver on a key requirement: getting the frontend app connected with [Amazon SageMaker](https://aws.amazon.com/pm/sagemaker/)—the backend managed cloud service that enables app developers to create, train, and deploy machine learning models.

"Our prototype worked well with Amazon Web Services (AWS), and our model was already trained," says LaVonda. "But we needed to expose the model to SageMaker to ensure we could scale our services as user activity spikes." But without prior experience with SageMaker, working through the documentation proved somewhat difficult for the Eyegage team. That's when LaVonda turned to AWS for help.

## AWS facilitates partnerships via Impact Accelerator program

Via her participation in the Black Founders cohort for the [AWS Impact Accelerator Program](https://aws-startup-lofts.com/amer/program/accelerators/black-founders), LaVonda gained access to personalized coaching, capital funding, and technical solutions. This connected EyeGage to [Avahi](https://www.avahitech.com/), a cloud-first consulting company and [AWS Global Startup Program partner](https://aws.amazon.com/partners/programs/global-startup/).

"Avahi impressed us with their knowledge about machine learning models and their understanding of our business," says LaVonda. "More importantly, they presented previous SageMaker projects they had taken on that were similar to what we needed. That gave us confidence Avahi could do the job."

Avahi layered the code of the machine learning model in SageMaker to expose it as a seamless API to end users of the EyeGage mobile app. This included updating the model code so it can be exposed as an event-driven machine learning inference. Avahi also layered the model with additional services like [AWS Lambda](https://aws.amazon.com/lambda/) for serverless computing and [Amazon API Gateway](https://aws.amazon.com/api-gateway/), a managed service that simplifies creating and maintaining APIs.

![LaVonda meeting with a coach at the AWS Startup Loft in New York to finalize her pitch for Investor Day](https://d22k7geae6sy8h.cloudfront.net/files/649baa831326f70008dadf89/8ljf5yuw5-JML_STUDIO_L1007508-Joseph-Michael-Lopez.jpg)

## Scaling to save lives

With the machine learning model exposed, the frontend app could better scale to provide contactless, non-invasive, objective/unbiased, secure, accurate, and quick drug screening results.

By pursuing this partnership, Eyegage, with Avahi's assistance, was also able to streamline the collection of end user data (such as identity and location), which allows the app to compare current and past scanning results and provide users with additional valuable information about their condition.

"Avahi also helped encode the AWS backend to receive JSON web tokens," adds LaVonda. "This gives us a more secure way to send data back and forth, which is critical, given the sensitivity of the information we process for our customers."

![LaVonda meeting with her technical mentor in Seattle during week 1 of the Impact Accelerator for Black Founders](https://d22k7geae6sy8h.cloudfront.net/files/649baaa81326f70008dadf8a/8ljf5zqaw-LaVonda-meeting-with-her-technical-mentor-in-Seattle-during-week-1-of-the-Impact-Accelerator-for-Black-Founders.jpg)

## What's next for Eyegage?

EyeGage is actively researching and updating its mobile application to include features to improve and assist in individual and community safety to decrease accidents. New application features, including Should I Drive? and FriendGage, promotes easy ways for accountability and accessibility to understand impairment levels.

There may also be a potential use for the company's dataset beyond its immediate use for detecting substances in the body. "You can identify someone by their eyes or diagnose illnesses, concussions or diabetes. Or, you can tell something like if you've had caffeine, depending on how it responds to light." LaVonda adds. "Monitoring eye behavior can be used for so much."

Explore more content that celebrates the achievements of Black innovators, such as:

- [AWS Startups Twitter stories](https://twitter.com/search?f=top&q=(%23BlackHistoryMonth)%20(from%3AAWSStartups)&src=typed_query) of inspiring, innovative, and game-changing Black founders
- [CareCoPilot founder Alyse Dunn wins big after AWS Impact Accelerator](https://aws.amazon.com/blogs/startups/carecopilot-founder-alyse-dunn-wins-big-after-aws-impact-accelerator/)
- [Shining a light on Black excellence: three founders share their stories](https://aws.amazon.com/blogs/startups/shining-a-light-on-black-excellence-three-founders-share-their-stories/)
- [How Resilia is helping nonprofits to build capacity through SaaS](https://aws.amazon.com/blogs/startups/how-resilia-is-helping-nonprofits-to-build-capacity-through-saas/)

---

> **Author: Bonnie McClure**

Bonnie is an editor specializing in creating accessible, engaging content for all audiences and platforms. She is dedicated to delivering comprehensive editorial guidance to provide a seamless user experience. When she's not advocating for the Oxford comma, you can find her spending time with her two large dogs, practicing her sewing skills, or testing out new recipes in the kitchen.
