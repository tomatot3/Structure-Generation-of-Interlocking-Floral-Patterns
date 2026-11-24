# Appearance generation

The collection contains 500 separately generated blue-and-white floral-scroll images. Each request used one selected structure PNG and the full text in `data/paired_renderings/prompts/author_prompt_v1.txt`. The archived submitted text is identical across all 500 requests.

The author supplied the prompt. It specifies the appearance style and allows small leaves and curls along existing paths. The same structure and rendering filenames identify a pair. The index links each input to editable geometry and recorded generation controls.

The author submitted the input image and prompt through ChatGPT’s image-generation tool. Pair records identify the route as `builtin_image_gen` and retain the input, prompt and original output.

To create a new image, submit a single PNG with the archived prompt to the chosen image service, save the returned original image and record the service/version supplied by that service. A local Python script can prepare inputs and indices but does not itself grant access to subscription image generation. All completed outputs are included here; browsing and structural analysis require no image-generation account.

The original 30-image evaluation used five model routes and has separate rating records in D3. It is not an evaluation of these 500 new pairs.
