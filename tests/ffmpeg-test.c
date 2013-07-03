// compile:
// gcc -lavformat -lavcodec -lavutil -g ffmpeg-test.c


// example code:
// https://github.com/FFmpeg/FFmpeg/blob/master/doc/examples/filtering_audio.c
// http://code.google.com/p/chromium-source-browsing/source/browse/ffmpeg.c?repo=third-party--ffmpeg
// http://dranger.com/ffmpeg/tutorial03.html
// http://ffmpeg.org/doxygen/trunk/ffplay_8c-source.html
// https://github.com/FFmpeg/FFmpeg/blob/master/ffplay.c

// void av_register_all(void);
// void avcodec_register_all(void);

// int avformat_open_input(AVFormatContext **ps, const char *filename, AVInputFormat *fmt, AVDictionary **options);
// fmt can be NULL (for autodetect).
// options can be NULL.
// close with av_close_input_file

// int av_read_play(AVFormatContext *s);

// int av_read_frame(AVFormatContext *s, AVPacket *pkt);
// returns encoded packet
// avcodec_decode_audio4

// int avcodec_decode_audio4(AVCodecContext *avctx, AVFrame *frame,
//                           int *got_frame_ptr, AVPacket *avpkt);

// int av_seek_frame(AVFormatContext *s, int stream_index, int64_t timestamp,
//                   int flags);



// void avformat_close_input(AVFormatContext **s);

// for cparser demo, see: https://github.com/albertz/PySDL/blob/master/SDL/__init__.py
// for reading/decoding, see: https://github.com/FFmpeg/FFmpeg/blob/master/doc/examples/filtering_audio.c


#include <libavformat/avformat.h>
#include <libavcodec/avcodec.h>
// link against libavcodec.dylib, libavformat.dylib

#include <stdarg.h>
#include <unistd.h>

void error(const char* fmt, ...) {
	va_list argptr;
	va_start(argptr, fmt);
	vfprintf(stderr, fmt, argptr);
	va_end(argptr);
	fprintf(stderr, "\n");
	_exit(1);
}

void openFile(const char* fn) {
	AVFormatContext* formatCtx = NULL;
	int ret = 0;
	ret = avformat_open_input(&formatCtx, fn, NULL, NULL);
	if(ret != 0) error("avformat_open_input returned %i", ret);
	ret = avformat_find_stream_info(formatCtx, NULL);
	if(ret != 0) error("avformat_find_stream_info returned %i", ret);

	AVCodec* dec = NULL;
	ret = av_find_best_stream(formatCtx, AVMEDIA_TYPE_AUDIO, -1, -1, &dec, 0);
	if(ret < 0) error("av_find_best_stream returned %i", ret);

	printf("codec: %i, %s, %s\n", dec->id, dec->name, dec->long_name);
	
	int si = ret;
	//print "stream index/num:", si, formatCtx.contents.nb_streams
	AVStream* stream = formatCtx->streams[si];

	// not sure if I'm supposed to alloc or not...
	//codecCtx = av.avcodec_alloc_context3(dec)
	AVCodecContext* codecCtx = stream->codec; // AVCodecContext
	if(!codecCtx) error("codec is NULL");
	ret = avcodec_open2(codecCtx, dec, NULL);
	if(ret != 0) error("avcodec_open2 returned %i", ret);
	
	printf("channels: %i\n", codecCtx->channels);
	printf("samplerate: %i\n", codecCtx->sample_rate);
	
	// somehow these are all invalid?
	//print "codec id:", codecCtx.contents.codec_id.value
	//name = av.avcodec_get_name(codecCtx.contents.codec_id.value)
	//name = ctypes.cast(name, ctypes.c_char_p)
	//print "codec name:", name.value
	//print codecCtx.contents.codec_type, codecCtx.contents.codec_type.value, codecCtx.contents.codec_type == av.AVMEDIA_TYPE_AUDIO
	
	// close with av_close_input_file

	ReSampleContext* resampleCtx = av_audio_resample_init(
		2, codecCtx->channels,
		44100, codecCtx->sample_rate,
		AV_SAMPLE_FMT_S16, codecCtx->sample_fmt,
		16, // filter len
		10, // log2 phase count
		1, // linear
		0.8 // cutoff
	);

	if(!resampleCtx) error("failed to init resampler");
	// audio_resample_close
	
	AVPacket packet;
	AVFrame frame;
	//pprint(dir(frame))

	int got_frame = 0;
	int numframes = 0;
	const int frameBufferSize = ((AVCODEC_MAX_AUDIO_FRAME_SIZE * 3) / 2);
	short frameBufferConverted[frameBufferSize];
	while(1) {
		ret = av_read_frame(formatCtx, &packet);
		if(ret < 0) break;
		if(packet.stream_index != si) continue;
		
		avcodec_get_frame_defaults(&frame);
		ret = avcodec_decode_audio4(codecCtx, &frame, &got_frame, &packet);
		if(ret < 0) {
			printf("error on decoding\n");
			continue;
		}
		if(!got_frame) continue;
		
		//pprint(dir(frame))
		numframes += 1;
		int dataSize = av_samples_get_buffer_size(
			NULL, codecCtx->channels,
			frame.nb_samples, codecCtx->sample_fmt,
			1);
		int newSamplesDecoded = dataSize / av_get_bytes_per_sample(codecCtx->sample_fmt);
		//print frameBufferConverted, frame.data, newSamplesDecoded
		ret = 0;
		//ret = audio_resample(resampleCtx, frameBufferConverted, frame.data, newSamplesDecoded);
		if(ret < 0) {
			printf("error on resampling\n");
			continue;
		}
		
		
	}
	
	printf("numframes: %i\n", numframes);
	
}

void test() {
	const char* fn = "/Users/az/Music/Electronic/One Day_Reckoning Song (Wankelmut Remix) - Asaf Avidan & the Mojos.mp3";
	//fn = "/Users/az/Music/Electronic/Von Paul Kalkbrenner - Aaron.mp3"
	/*f =*/ openFile(fn);
}

int main() {
	printf("call ffmpeg init\n");
	avcodec_register_all();
	av_register_all();
	
	test();
}
