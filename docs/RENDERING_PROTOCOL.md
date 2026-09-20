# Appearance generation

The collection contains 500 separately generated blue-and-white floral-scroll images. Each request used one selected structure PNG and the full text in `data/paired_renderings/prompts/author_prompt_v1.txt`. The archived submitted text is identical across all 500 requests.

The author supplied the prompt. It specifies the appearance style and allows small leaves and curls along existing paths. The same structure and rendering filenames identify a pair. The index links each input to editable geometry and recorded generation controls.

The actual route was the built-in `image_gen` tool in Codex, using the author's subscription. The conversation model and the image-generation service are separate. The service did not return its underlying model identifier or random seed, so those values are not inferred from the conversation model. No exact pixel-reproduction setting is available for the appearance outputs.

To create a new image, submit a single PNG with the archived prompt to the chosen image service, save the returned original image and record the service/version supplied by that service. A local Python script can prepare inputs and indices but does not itself grant access to subscription image generation. All completed outputs are included here; browsing and structural analysis require no image-generation account.

The original 30-image evaluation used five model routes and has separate rating records in D3. It is not an evaluation of these 500 new pairs.
